import { FlickerCanvas } from "../ssvep/FlickerCanvas";
import { TRANSPORT_TILES } from "../ssvep/frequencies";

interface TransportLayerProps {
  highlightedTileId: string | null;
}

export function TransportLayer({ highlightedTileId }: TransportLayerProps) {
  return <FlickerCanvas tiles={TRANSPORT_TILES} highlightedTileId={highlightedTileId} />;
}
