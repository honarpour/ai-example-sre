import { type DBSchema, type IDBPDatabase, openDB } from "idb"
import type { Investigation } from "./types"

interface InvestigatorDB extends DBSchema {
  investigations: {
    key: string
    value: Investigation
    indexes: { "by-created": string }
  }
}

let dbPromise: Promise<IDBPDatabase<InvestigatorDB>> | null = null

function getDb(): Promise<IDBPDatabase<InvestigatorDB>> {
  dbPromise ??= openDB<InvestigatorDB>("sre-investigator", 1, {
    upgrade(db) {
      const store = db.createObjectStore("investigations", { keyPath: "id" })
      store.createIndex("by-created", "created_at")
    },
  })
  return dbPromise
}

/** History persistence only — the backend's in-memory store is the source of
 * truth while a run is live. Every read/write here is wrapped defensively:
 * a private browsing session or blocked site data should degrade to "no
 * history" rather than break the app. */
export async function saveInvestigation(investigation: Investigation): Promise<void> {
  try {
    const db = await getDb()
    await db.put("investigations", investigation)
  } catch (err) {
    console.warn("Failed to persist investigation to IndexedDB", err)
  }
}

export async function listSavedInvestigations(): Promise<Investigation[]> {
  try {
    const db = await getDb()
    const all = await db.getAllFromIndex("investigations", "by-created")
    return all.reverse()
  } catch (err) {
    console.warn("Failed to read investigations from IndexedDB", err)
    return []
  }
}

export async function getSavedInvestigation(id: string): Promise<Investigation | undefined> {
  try {
    const db = await getDb()
    return await db.get("investigations", id)
  } catch (err) {
    console.warn("Failed to read investigation from IndexedDB", err)
    return undefined
  }
}
