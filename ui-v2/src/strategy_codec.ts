export type AttributeId = "intelligence" | "strength" | "agility";
export type AttributeWire = "int" | "str" | "agi";

const ATTRIBUTE_ID_TO_WIRE: Record<AttributeId, AttributeWire> = {
  intelligence: "int",
  strength: "str",
  agility: "agi",
};

const ATTRIBUTE_WIRE_TO_ID: Record<AttributeWire, AttributeId> = {
  int: "intelligence",
  str: "strength",
  agi: "agility",
};

/** Convert UI ids and already-normalized wire values to one unique wire list. */
export function normalizeAttributeValues(values: Iterable<unknown>): AttributeWire[] {
  const out: AttributeWire[] = [];
  for (const value of values) {
    if (typeof value !== "string") continue;
    const wire = (ATTRIBUTE_ID_TO_WIRE as Record<string, AttributeWire | undefined>)[value]
      ?? (ATTRIBUTE_WIRE_TO_ID[value as AttributeWire] ? value as AttributeWire : undefined);
    if (wire && !out.includes(wire)) out.push(wire);
  }
  return out;
}

/** Convert backend wire values to the ids used by the editable UI state. */
export function restoreAttributeIds(values: Iterable<unknown>): Set<AttributeId> {
  const out = new Set<AttributeId>();
  for (const value of values) {
    if (typeof value !== "string") continue;
    const id = ATTRIBUTE_WIRE_TO_ID[value as AttributeWire]
      ?? ((ATTRIBUTE_ID_TO_WIRE as Record<string, AttributeWire | undefined>)[value]
        ? value as AttributeId
        : undefined);
    if (id) out.add(id);
  }
  return out;
}
