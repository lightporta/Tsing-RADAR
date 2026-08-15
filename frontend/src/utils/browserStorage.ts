export const LOCAL_DATA_VERSION = 1

export const USER_PROFILE_STORAGE_KEY = 'tsing-radar:user-profile'
export const CHAT_HISTORY_STORAGE_KEY = 'tsing-radar:chat-history'

interface VersionedLocalData<T> {
  version: number
  updatedAt: number
  data: T
}

export type LocalStorageWriteResult =
  | { ok: true }
  | { ok: false; reason: 'unavailable' | 'quota' | 'unknown' }

function getStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function readVersionedLocalData<T>(
  key: string,
  validate: (value: unknown) => value is T,
): T | null {
  const storage = getStorage()
  if (!storage) return null

  try {
    const raw = storage.getItem(key)
    if (!raw) return null
    const envelope = JSON.parse(raw) as Partial<VersionedLocalData<unknown>>
    if (
      envelope.version !== LOCAL_DATA_VERSION ||
      typeof envelope.updatedAt !== 'number' ||
      !validate(envelope.data)
    ) {
      storage.removeItem(key)
      return null
    }
    return envelope.data
  } catch {
    try {
      storage.removeItem(key)
    } catch {
      // 浏览器禁用本地存储时，不影响页面继续使用内存状态。
    }
    return null
  }
}

export function writeVersionedLocalData<T>(key: string, data: T): LocalStorageWriteResult {
  const storage = getStorage()
  if (!storage) return { ok: false, reason: 'unavailable' }

  try {
    const envelope: VersionedLocalData<T> = {
      version: LOCAL_DATA_VERSION,
      updatedAt: Date.now(),
      data,
    }
    storage.setItem(key, JSON.stringify(envelope))
    return { ok: true }
  } catch (error) {
    if (
      error instanceof DOMException &&
      (error.name === 'QuotaExceededError' || error.name === 'NS_ERROR_DOM_QUOTA_REACHED')
    ) {
      return { ok: false, reason: 'quota' }
    }
    return { ok: false, reason: 'unknown' }
  }
}

export function removeLocalData(key: string) {
  const storage = getStorage()
  if (!storage) return
  try {
    storage.removeItem(key)
  } catch {
    // 清理失败时维持内存状态，交由调用方给出可理解的提示。
  }
}

export function clearTsingRadarLocalData() {
  removeLocalData(USER_PROFILE_STORAGE_KEY)
  removeLocalData(CHAT_HISTORY_STORAGE_KEY)
}
