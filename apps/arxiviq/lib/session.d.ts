export const SESSION_COOKIE: "__Host-arxiviq_session";

export type SessionClaims = {
  iss: "arxiviq";
  aud: "jarvisd";
  caps: string[];
  iat: number;
  exp: number;
  sid: string;
  sub: string;
  repo: string;
};

export function validatePublicOrigin(origin: unknown): string | null;

export function validateSessionConfig(
  env?: Record<string, string | number | undefined>,
): void;

export function createSession(
  input: { agent: string; pairExp: number; now?: number },
  env?: Record<string, string | number | undefined>,
): { token: string; claims: SessionClaims; maxAge: number };

export function readSession(
  token: string | undefined,
  env?: Record<string, string | number | undefined>,
): SessionClaims | null;
