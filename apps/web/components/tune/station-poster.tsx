import { memo, useMemo } from "react";

import { composeCover } from "../../lib/cover/styled";
import { posterTransform, STATION_POSTERS } from "../../lib/station-poster";
import type { StationId } from "../../lib/stations";
import { TypeCover } from "../cover/type-cover";

/** A station's picture on the tuner card (lib/station-poster): its cover, cropped to fill the square. */
export const StationPoster = memo(function StationPoster({ stationId }: { stationId: StationId }) {
  const spec = STATION_POSTERS[stationId];
  const params = useMemo(() => ({ stationId, seed: spec.seed, heading: "", bare: true, pin: spec.pin }), [stationId, spec]);
  const background = useMemo(() => {
    const composed = composeCover(params);
    return composed.kind === "styled" ? composed.view.rootBg : "#ddd";
  }, [params]);
  const { transform, transformOrigin } = posterTransform(spec);
  return (
    <div style={{ width: "100%", height: "100%", background, overflow: "hidden" }}>
      <div style={{ width: "100%", height: "100%", transform, transformOrigin }}>
        <TypeCover params={params} radius={0} />
      </div>
    </div>
  );
});
