export interface LSLStatus {
  stream_name: string;
  connected: boolean;
  fs: number;
  channel_count: number;
  channel_labels: string[];
  occipital_indices: number[];
  hostname: string;
}
