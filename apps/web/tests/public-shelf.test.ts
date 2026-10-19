import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({ default: (props: Record<string, unknown>) => createElement("a", { ...props, href: String(props.href) }) }));
vi.mock("../lib/api", () => ({ api: { publicShelf: vi.fn() } }));
vi.mock("../components/cover/type-cover", () => ({ TypeCover: () => null }));

import { PublicShelf } from "../components/home/public-shelf";
import { api } from "../lib/api";
import { usePublicShelf } from "../lib/public-shelf";
import type { PublicShelfItem, PublicShelfPage } from "../lib/types";

const item = (n: number): PublicShelfItem => ({
  id: `pub-${String(n).repeat(32)}`, title: `别人的节目 ${n}`, cover_title: null, station: "night", estimated_duration_seconds: 2100,
});
const page = (ids: number[], hasMore: boolean): PublicShelfPage => ({ items: ids.map(item), has_more: hasMore });

let root: Root;
let host: HTMLDivElement;

function Probe({ identity, enabled = true }: { identity: string | null; enabled?: boolean }) {
  const shelf = usePublicShelf(identity, enabled);
  return createElement(PublicShelf, { shelf });
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api.publicShelf).mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const mount = async (props: { identity: string | null; enabled?: boolean } = { identity: null }) => {
  await act(async () => root.render(createElement(Probe, props)));
  await act(async () => { await Promise.resolve(); });
};
const titles = () => [...host.querySelectorAll(".pick-title")].map((node) => node.textContent);
const press = () => act(async () => { host.querySelector<HTMLButtonElement>(".pick-refresh")!.click(); });
const settle = () => act(async () => { await Promise.resolve(); });

describe("大家都在听", () => {
  it("shows the programmes as links to their own pages, with the station and length", async () => {
    vi.mocked(api.publicShelf).mockResolvedValue(page([1, 2, 3], true));
    await mount();
    expect(titles()).toEqual(["别人的节目 1", "别人的节目 2", "别人的节目 3"]);
    const first = host.querySelector<HTMLAnchorElement>("a.pick")!;
    expect(first.getAttribute("href")).toBe(`/program/pub-${"1".repeat(32)}`);
    expect(first.textContent).toContain("夜里 · 35 分钟");
    expect(host.querySelector("h2")?.textContent).toBe("大家都在听");
    expect(host.querySelector(".pick-refresh")).not.toBeNull();
  });

  it("leaves the whole section out when there is nothing to show, or the shelf cannot be reached", async () => {
    vi.mocked(api.publicShelf).mockResolvedValue(page([], false));
    await mount();
    expect(host.querySelector("section")).toBeNull();

    vi.mocked(api.publicShelf).mockRejectedValue(new Error("down"));
    await mount({ identity: "user-1" });
    expect(host.querySelector("section")).toBeNull();
  });

  it("換一批 asks for others than the ones shown, with placeholders meanwhile, and ends when nothing is left", async () => {
    vi.mocked(api.publicShelf).mockResolvedValueOnce(page([1, 2, 3], true));
    await mount();
    let resolve: (value: PublicShelfPage) => void = () => undefined;
    vi.mocked(api.publicShelf).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    await press();
    expect(api.publicShelf).toHaveBeenLastCalledWith([item(1).id, item(2).id, item(3).id]);
    expect(host.querySelectorAll(".pick-skeleton").length).toBeGreaterThan(0);
    expect(host.querySelector<HTMLButtonElement>(".pick-refresh")!.disabled).toBe(true);

    await act(async () => resolve(page([4, 5], false)));
    await settle();
    expect(titles()).toEqual(["别人的节目 4", "别人的节目 5"]);
    expect(host.querySelector(".pick-refresh")).toBeNull();
    expect(host.querySelector(".pick-end")?.textContent).toBe("已经看完了");
  });

  it("keeps the rail and says it is the end when 换一批 finds nothing more", async () => {
    vi.mocked(api.publicShelf).mockResolvedValueOnce(page([1, 2, 3], true));
    await mount();
    vi.mocked(api.publicShelf).mockResolvedValueOnce(page([], false));
    await press();
    await settle();
    expect(titles()).toEqual(["别人的节目 1", "别人的节目 2", "别人的节目 3"]);
    expect(host.querySelector(".pick-end")).not.toBeNull();
  });

  it("starts again for another listener, and asks nothing before the session is known", async () => {
    vi.mocked(api.publicShelf).mockResolvedValue(page([1, 2, 3], true));
    await mount({ identity: null, enabled: false });
    expect(api.publicShelf).not.toHaveBeenCalled();
    await mount({ identity: null, enabled: true });
    expect(api.publicShelf).toHaveBeenCalledTimes(1);
    await mount({ identity: "user-1", enabled: true });
    expect(api.publicShelf).toHaveBeenCalledTimes(2);
    // The new listener starts from the first batch: nothing is excluded as "shown".
    expect(api.publicShelf).toHaveBeenLastCalledWith();
  });
});
