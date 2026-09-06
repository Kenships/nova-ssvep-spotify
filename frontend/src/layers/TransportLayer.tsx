import { FlickerCanvas } from "../ssvep/FlickerCanvas";
import type { FlickerMode } from "../ssvep/flickerModes";
import { TRANSPORT_TILES } from "../ssvep/frequencies";

interface TransportLayerProps {
  highlightedTileId: string | null;
  mode: FlickerMode;
  onTileActivate: (tileId: string) => Promise<boolean>;
}

export function TransportLayer({ highlightedTileId, mode, onTileActivate }: TransportLayerProps) {
  return (
    <FlickerCanvas
      tiles={TRANSPORT_TILES}
      highlightedTileId={highlightedTileId}
      mode={mode}
      onTileActivate={onTileActivate}
    />
  );
}
