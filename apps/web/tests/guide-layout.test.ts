import { describe, expect, it } from "vitest";

import { BUBBLE_WIDTH, placeBubble, SPOT_PAD } from "../lib/guide/layout";

const phone = { width: 390, height: 844 };

describe("guide card placement", () => {
  it("sits below the lit element, with its arrow pointing at the middle of it", () => {
    const place = placeBubble({ left: 20, top: 171, width: 350, height: 162 }, phone);
    expect(place.side).toBe("below");
    expect(place.width).toBe(BUBBLE_WIDTH);
    expect(place.edge).toBe(171 + 162 + SPOT_PAD + 14);
    expect(place.left).toBe(40);
    expect(place.arrow).toBe(195 - 40 - 8);
  });

  it("sits above when asked, measured from the bottom of the screen", () => {
    const place = placeBubble({ left: 138, top: 769, width: 114, height: 49 }, phone, "above");
    expect(place.side).toBe("above");
    expect(place.edge).toBe(844 - (769 - SPOT_PAD - 14));
  });

  it("flips to the side with room", () => {
    expect(placeBubble({ left: 20, top: 60, width: 100, height: 40 }, phone, "above").side).toBe("below");
    expect(placeBubble({ left: 20, top: 760, width: 100, height: 40 }, phone, "below").side).toBe("above");
  });

  it("stays on the screen and keeps its arrow on the card", () => {
    const edge = placeBubble({ left: 330, top: 69, width: 40, height: 40 }, phone);
    expect(edge.left + edge.width).toBe(390 - 16);
    expect(edge.arrow).toBeLessThanOrEqual(edge.width - 38);
    const left = placeBubble({ left: 0, top: 300, width: 20, height: 40 }, phone);
    expect(left.left).toBe(16);
    expect(left.arrow).toBeGreaterThanOrEqual(22);
  });

  it("narrows the card on a small screen, and centres it when nothing is lit", () => {
    const small = { width: 320, height: 568 };
    const centred = placeBubble(null, small);
    expect(centred.side).toBe("center");
    expect(centred.width).toBe(320 - 32);
    expect(centred.left).toBe(16);
  });
});
