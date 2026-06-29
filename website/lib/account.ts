import { createHash, pbkdf2Sync, randomBytes } from "crypto";

export type AccountUser = {
  id: string;
  email: string;
  api_key: string;
  credits: number;
  github_token: string;
  linear_api_key: string;
  linear_team_id: string;
  notify_email: string;
  password_hash: string;
  salt: string;
  created_at: string;
};

export const FREE_CREDITS = 500_000;

export function hashPassword(password: string, salt: string): string {
  return pbkdf2Sync(password, salt, 120_000, 32, "sha256").toString("hex");
}

export function newApiKey(): string {
  return `crt_live_${randomBytes(18).toString("base64url")}`;
}

export function exportProfile(user: AccountUser) {
  return {
    email: user.email,
    api_key: user.api_key,
    credits: user.credits,
    github_connected: Boolean(user.github_token),
    linear_connected: Boolean(user.linear_api_key),
    linear_team_id: user.linear_team_id,
    notify_email: user.notify_email,
    usage: [] as { service: string; units: number; detail: string; created_at: string }[],
  };
}

export function createUser(email: string, password: string): AccountUser {
  const salt = randomBytes(16).toString("hex");
  return {
    id: randomBytes(8).toString("hex"),
    email: email.trim().toLowerCase(),
    api_key: newApiKey(),
    credits: FREE_CREDITS,
    github_token: "",
    linear_api_key: "",
    linear_team_id: "",
    notify_email: "",
    password_hash: hashPassword(password, salt),
    salt,
    created_at: new Date().toISOString(),
  };
}

export function verifyPassword(user: AccountUser, password: string): boolean {
  return hashPassword(password, user.salt) === user.password_hash;
}

/** In-memory fallback when Vercel KV is not linked (local dev). */
const memory = new Map<string, AccountUser>();

function memKey(kind: string, value: string) {
  return `${kind}:${value}`;
}

async function kvAvailable(): Promise<boolean> {
  return Boolean(process.env.KV_REST_API_URL && process.env.KV_REST_API_TOKEN);
}

async function kvGet<T>(key: string): Promise<T | null> {
  if (!(await kvAvailable())) {
    return (memory.get(key) as T) ?? null;
  }
  const { kv } = await import("@vercel/kv");
  return (await kv.get<T>(key)) ?? null;
}

async function kvSet(key: string, value: unknown): Promise<void> {
  if (!(await kvAvailable())) {
    memory.set(key, value as AccountUser);
    return;
  }
  const { kv } = await import("@vercel/kv");
  await kv.set(key, value);
}

async function kvDel(key: string): Promise<void> {
  if (!(await kvAvailable())) {
    memory.delete(key);
    return;
  }
  const { kv } = await import("@vercel/kv");
  await kv.del(key);
}

export async function saveUser(user: AccountUser): Promise<void> {
  await kvSet(`user:id:${user.id}`, user);
  await kvSet(`user:email:${user.email}`, user.id);
  await kvSet(`user:apikey:${user.api_key}`, user.id);
}

export async function getUserByEmail(email: string): Promise<AccountUser | null> {
  const id = await kvGet<string>(`user:email:${email.trim().toLowerCase()}`);
  if (!id) return null;
  return kvGet<AccountUser>(`user:id:${id}`);
}

export async function getUserByApiKey(apiKey: string): Promise<AccountUser | null> {
  const id = await kvGet<string>(`user:apikey:${apiKey.trim()}`);
  if (!id) return null;
  return kvGet<AccountUser>(`user:id:${id}`);
}

export async function registerUser(email: string, password: string): Promise<AccountUser> {
  if (!email.trim() || !password) throw new Error("Email and password required");
  const existing = await getUserByEmail(email);
  if (existing) throw new Error("Email already registered");
  const user = createUser(email, password);
  await saveUser(user);
  return user;
}

export async function loginUser(email: string, password: string): Promise<AccountUser> {
  const user = await getUserByEmail(email);
  if (!user || !verifyPassword(user, password)) throw new Error("Invalid email or password");
  return user;
}

export async function updateCredentials(
  user: AccountUser,
  patch: Partial<Pick<AccountUser, "github_token" | "linear_api_key" | "linear_team_id" | "notify_email">>
): Promise<AccountUser> {
  const next = { ...user, ...patch };
  await saveUser(next);
  return next;
}

export async function deductCredits(userId: string, units: number, service: string): Promise<number> {
  const user = await kvGet<AccountUser>(`user:id:${userId}`);
  if (!user) return 0;
  user.credits = Math.max(0, user.credits - units);
  await saveUser(user);
  const usageKey = `usage:${userId}:${Date.now()}`;
  await kvSet(usageKey, { user_id: userId, service, units, created_at: new Date().toISOString() });
  return user.credits;
}

export function authUserFromHeaders(authorization: string, xApiKey: string): Promise<AccountUser | null> {
  let token = xApiKey.trim();
  if (authorization.toLowerCase().startsWith("bearer ")) token = authorization.slice(7).trim();
  if (!token) return Promise.resolve(null);
  return getUserByApiKey(token);
}
