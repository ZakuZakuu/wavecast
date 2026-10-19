import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { StationTile } from "../components/home/station-tile";
import { formatFreq, STATIONS } from "../lib/stations";

describe("station tile", () => {
  it.each(STATIONS)("links $name to its tuner with an icon and its texture", (station) => {
    const html = renderToStaticMarkup(createElement(StationTile, { station }));
    expect(html).toContain(`href="/tune?station=${station.id}"`);
    expect(html).toContain(`aria-label="FM ${formatFreq(station.freq)} ${station.name}，${station.line}"`);
    expect(html).toContain(station.name);
    // The icon and its enlarged copy are both drawn.
    expect(html.match(/<path /g)!.length).toBeGreaterThanOrEqual(4);
    expect(html).toContain("station-tile-ghost");
    expect(html).toContain(station.deep);
  });
});
