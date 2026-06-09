import { atom, map } from "nanostores";

export const $config = atom<Record<string, unknown>>({});
export const $configDirty = atom<boolean>(false);

export const $configMeta = map<{ loading: boolean; saving: boolean; error: string | null }>({
  loading: false,
  saving: false,
  error: null,
});

export function setConfigValue(key: string, value: unknown): void {
  const next = { ...$config.get(), [key]: value };
  $config.set(next);
  $configDirty.set(true);
}