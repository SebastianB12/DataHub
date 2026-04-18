import pg from "pg";
import { readFileSync } from "fs";
import { config } from "dotenv";

config({ path: ".env" });

const ref = new URL(process.env.SUPABASE_URL).hostname.split(".")[0];
const password = process.env.SUPABASE_DB_PW;

const client = new pg.Client({
  host: `db.${ref}.supabase.co`,
  port: 5432,
  database: "postgres",
  user: "postgres",
  password,
  ssl: { rejectUnauthorized: false },
});

try {
  await client.connect();
  console.log("Connected to Supabase PostgreSQL");

  const sql = readFileSync("supabase/migrations/001_initial_schema.sql", "utf8");
  await client.query(sql);
  console.log("Migration completed successfully");
} catch (err) {
  console.error("Migration failed:", err.message);
  process.exit(1);
} finally {
  await client.end();
}
