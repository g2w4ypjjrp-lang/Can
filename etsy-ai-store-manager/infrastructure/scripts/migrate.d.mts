export function migrate(opts: {
  connectionString: string | undefined;
  reset?: boolean;
  withShim?: boolean;
  log?: (msg: string) => void;
}): Promise<{ applied: number; total: number }>;
