import { FlickerCanvas } from "../ssvep/FlickerCanvas";
import type { FlickerMode } from "../ssvep/flickerModes";
import { MOOD_TILES } from "../ssvep/frequencies";

interface MoodLayerProps {
  highlightedTileId: string | null;
  mode: FlickerMode;
  onTileActivate: (tileId: string) => Promise<boolean>;
}

export function MoodLayer({ highlightedTileId, mode, onTileActivate }: MoodLayerProps) {
  return (
    <FlickerCanvas
      tiles={MOOD_TILES}
      highlightedTileId={highlightedTileId}
      mode={mode}
      onTileActivate={onTileActivate}
    />
  );
}
