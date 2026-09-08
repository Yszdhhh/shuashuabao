import { describe, expect, it } from "vitest";
import { normalizeAttributeValues, restoreAttributeIds } from "../src/strategy_codec";

describe("strategy attribute codec", () => {
  it("deduplicates mixed UI and wire values before sending a patch", () => {
    expect(normalizeAttributeValues(["int", "intelligence", "str", "int", "unknown"]))
      .toEqual(["int", "str"]);
  });

  it("restores backend wire values to the editable UI ids", () => {
    expect([...restoreAttributeIds(["int", "intelligence", "agi", "unknown"])])
      .toEqual(["intelligence", "agility"]);
  });
});
