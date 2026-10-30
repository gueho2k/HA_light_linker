"""Zigbee2MQTT helpers: groups for simultaneous switching, ZHA -> Z2M move."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import Z2M_BASE_TOPIC

if TYPE_CHECKING:
    from .models import Link

_LOGGER = logging.getLogger(__name__)


def ieee_hex(value: str) -> str:
    """'94:ec:32:..' or '0x94ec32..' -> '0x94ec32...'."""
    value = value.strip().lower()
    if value.startswith("0x"):
        return value
    return "0x" + value.replace(":", "")


def device_ieee(device: dr.DeviceEntry) -> tuple[str, str] | None:
    """(stack, ieee as 0x...) of a ZHA or Zigbee2MQTT device."""
    for ident in device.identifiers:
        if len(ident) < 2:
            continue
        domain, value = ident[0], str(ident[1])
        if domain == "zha":
            return "zha", ieee_hex(value)
        if domain == "mqtt" and value.startswith("zigbee2mqtt_0x"):
            return "z2m", value.removeprefix("zigbee2mqtt_")
    return None


def find_device(hass: HomeAssistant, identifier: tuple[str, str]) -> dr.DeviceEntry | None:
    """Device by identifier.

    Since HA 2026.8 identifiers are only unique per config entry: the new lookup
    takes the config entry, so every entry of the integration (mqtt, zha) is asked.
    Older versions only have async_get_device.
    """
    dev_reg = dr.async_get(hass)
    lookup = getattr(dev_reg, "async_get_device_by_identifier", None)
    if lookup is not None:
        try:
            for entry in hass.config_entries.async_entries(identifier[0]):
                if found := lookup(identifier, config_entry_id=entry.entry_id):
                    return found
            return None
        except TypeError:
            pass  # different signature: fall back to the old lookup
    return dev_reg.async_get_device(identifiers={identifier})


def z2m_device(hass: HomeAssistant, ieee: str) -> dr.DeviceEntry | None:
    """The Zigbee2MQTT device with this IEEE, if paired there."""
    return find_device(hass, ("mqtt", f"zigbee2mqtt_{ieee_hex(ieee)}"))


class Z2MGroups:
    """Knows the Zigbee2MQTT groups and their light entities.

    Reads the retained topic <base>/bridge/groups. A link whose lights are
    exactly the members of a group is switched through the group: one multicast
    command, all lamps at once.
    """

    def __init__(self, hass: HomeAssistant, base_topic: str = Z2M_BASE_TOPIC) -> None:
        """Initialize."""
        self.hass = hass
        self.base = base_topic
        self._by_members: dict[frozenset[str], tuple[str, str]] = {}
        # group entity -> (friendly name, member IEEEs)
        self._groups: dict[str, tuple[str, list[str]]] = {}
        self._raw: list[dict[str, Any]] = []
        self._unsub: CALLBACK_TYPE | None = None

    async def async_start(self) -> None:
        """Subscribe if MQTT is available."""
        if "mqtt" not in self.hass.config.components:
            return
        from homeassistant.components import mqtt  # noqa: PLC0415

        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            return
        self._unsub = await mqtt.async_subscribe(
            self.hass, f"{self.base}/bridge/groups", self._message, qos=0
        )

    @callback
    def async_stop(self) -> None:
        """Unsubscribe."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _message(self, msg: Any) -> None:
        try:
            groups = json.loads(msg.payload)
        except (ValueError, TypeError):
            return
        if isinstance(groups, list):
            self.async_set_groups(groups)

    @callback
    def async_set_groups(self, groups: list[dict[str, Any]]) -> None:
        """Rebuild the member -> group map (also used by tests)."""
        self._raw = groups
        self.async_rebuild()

    @callback
    def async_rebuild(self) -> None:
        """Map groups to entities; skip groups we cannot map exactly."""
        ent_reg = er.async_get(self.hass)
        result: dict[frozenset[str], tuple[str, str]] = {}
        groups: dict[str, tuple[str, list[str]]] = {}
        for group in self._raw:
            gid = group.get("id")
            members = group.get("members") or []
            if gid is None:
                continue
            group_entity = ent_reg.async_get_entity_id("light", "mqtt", f"{gid}_light_{self.base}")
            if group_entity is None:
                continue
            groups[group_entity] = (
                str(group.get("friendly_name", gid)),
                [str(m.get("ieee_address")) for m in members if m.get("ieee_address")],
            )
            if len(members) < 2:
                continue
            member_entities = []
            for member in members:
                entity_id = ent_reg.async_get_entity_id(
                    "light", "mqtt", f"{member.get('ieee_address')}_light_{self.base}"
                )
                if entity_id is None:
                    break  # multi-endpoint device or not a light: no exact mapping
                member_entities.append(entity_id)
            else:
                result[frozenset(member_entities)] = (group_entity, group.get("friendly_name", str(gid)))
        self._by_members = result
        self._groups = groups

    def group_info(self, entity_id: str) -> tuple[str, list[str]] | None:
        """(friendly name, member IEEEs) of a Z2M group light entity."""
        return self._groups.get(entity_id)

    def group_for(self, lights: list[str]) -> tuple[str, str] | None:
        """(group entity, group name) if the lights are exactly one group."""
        if len(lights) < 2:
            return None
        return self._by_members.get(frozenset(lights))


# ------------------------------------------------------- native Zigbee targets


@callback
def native_target(hass: HomeAssistant, groups: Z2MGroups, entity_id: str) -> dict[str, Any] | None:
    """How to address a light natively.

    {"stack": "z2m", "name": friendly name, "members": [names]} or
    {"stack": "zha", "ieee": ..., "endpoint": int} or {"stack": "zha", "group": int}.
    """
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.domain != "light":
        return None
    unique = entry.unique_id or ""
    if entry.platform == "mqtt" and unique.endswith(f"_light_{Z2M_BASE_TOPIC}"):
        if info := groups.group_info(entity_id):
            name, members = info
            names = [n for ieee in members if (n := z2m_name(hass, ieee))]
            return {"stack": "z2m", "name": name, "members": names}
        ieee = unique.removesuffix(f"_light_{Z2M_BASE_TOPIC}")
        if ieee.startswith("0x") and (name := z2m_name(hass, ieee)):
            return {"stack": "z2m", "name": name, "members": [name]}
        return None
    if entry.platform == "zha":
        if unique.startswith("light_zha_group_0x"):
            try:
                return {"stack": "zha", "group": int(unique.removeprefix("light_zha_group_0x"), 16)}
            except ValueError:
                return None
        ieee, _, endpoint = unique.partition("-")
        if len(ieee) == 23 and endpoint:
            try:
                return {"stack": "zha", "ieee": ieee, "endpoint": int(endpoint.split("-")[0])}
            except ValueError:
                return None
    return None


@callback
def z2m_name(hass: HomeAssistant, ieee: str) -> str | None:
    """Zigbee2MQTT friendly name (= device name it announced) of a device."""
    device = z2m_device(hass, ieee)
    return device.name if device and device.name else None


# ---------------------------------------------------------------- ZHA -> Z2M


@callback
def ieee_of_entity(hass: HomeAssistant, entity_id: str) -> tuple[str, str] | None:
    """(stack, ieee) of the Zigbee device behind an entity."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.device_id is None:
        return None
    device = dr.async_get(hass).async_get(entry.device_id)
    return device_ieee(device) if device else None


def _target_ids(link: Link) -> list[str]:
    ids = list(link.targets.get("entity_id", []))
    for binding in link.bindings:
        if binding.get("targets"):
            ids += [e for e in binding["targets"].get("entity_id", []) if e not in ids]
    return ids


@callback
def update_hints(hass: HomeAssistant, links: list[Link], hints: dict[str, str]) -> bool:
    """Remember the IEEE of every ZHA entity a link uses; True if changed."""
    changed = False
    for link in links:
        idents = _target_ids(link)
        idents += [s.entity_id for s in link.sources if s.entity_id]
        for entity_id in idents:
            found = ieee_of_entity(hass, entity_id)
            if found and found[0] == "zha" and hints.get(entity_id) != found[1]:
                hints[entity_id] = found[1]
                changed = True
    return changed


def _z2m_entity(hass: HomeAssistant, ieee: str, domain: str) -> str | None:
    device = z2m_device(hass, ieee)
    if device is None:
        return None
    ent_reg = er.async_get(hass)
    if domain == "event":
        if entity_id := ent_reg.async_get_entity_id("event", "mqtt", f"{ieee}_action_{Z2M_BASE_TOPIC}"):
            return entity_id
    candidates = [
        e.entity_id
        for e in er.async_entries_for_device(ent_reg, device.id)
        if e.domain == domain and e.entity_category is None
    ]
    return candidates[0] if len(candidates) == 1 else None


@callback
def suggestions(hass: HomeAssistant, link: Link, hints: dict[str, str]) -> list[dict[str, Any]]:
    """What in this link can move from ZHA to an already paired Z2M device."""
    result: list[dict[str, Any]] = []
    for index, src in enumerate(link.sources):
        if src.device_ieee:  # ZHA remote
            if new := _z2m_entity(hass, ieee_hex(src.device_ieee), "event"):
                result.append({"kind": "source", "index": index, "old": src.device_ieee, "new": new})
    for entity_id in _target_ids(link):
        found = ieee_of_entity(hass, entity_id)
        if found and found[0] == "z2m":
            continue  # already on Z2M
        ieee = found[1] if found else hints.get(entity_id)
        if not ieee:
            continue
        if new := _z2m_entity(hass, ieee, entity_id.split(".", 1)[0]):
            if new != entity_id:
                result.append({"kind": "target", "old": entity_id, "new": new})
    return result
