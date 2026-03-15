import { createClient as createSupabaseClient } from "@supabase/supabase-js";
import type { Database } from "./database.types.js";

export function createClient(supabaseUrl: string, supabaseKey: string) {
  return createSupabaseClient<Database>(supabaseUrl, supabaseKey);
}
