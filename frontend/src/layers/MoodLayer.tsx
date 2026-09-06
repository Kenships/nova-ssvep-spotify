import { FlickerCanvas } from "../ssvep/FlickerCanvas";
import { MOOD_TILES } from "../ssvep/frequencies";

interface MoodLayerProps {
  highlightedTileId: string | null;
}

export function MoodLayer({ highlightedTileId }: MoodLayerProps) {
  return <FlickerCanvas tiles={MOOD_TILES} highlightedTileId={highlightedTileId} />;
}
