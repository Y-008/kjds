import { mutationOriginIsAllowed } from "../../../lib/identity-config";
import { resolveWebIdentity, WebIdentityError } from "../../../lib/web-identity";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

const forwardedRequestHeaders = ["accept", "content-type"];
const forwardedResponseHeaders = ["content-type", "content-disposition"];

async function forward(request: Request, context: RouteContext): Promise<Response> {
  const apiBase = process.env.KJDS_API_URL ?? "http://127.0.0.1:8000";
  const csrfMarkerAccepted = request.headers.get("x-kjds-csrf") === "same-origin-fetch";
  if (!csrfMarkerAccepted && !mutationOriginIsAllowed(request)) {
    return Response.json({ detail: "Cross-site or originless mutations are not allowed" }, { status: 403 });
  }

  let apiKey: string;
  try {
    apiKey = (await resolveWebIdentity()).apiKey;
  } catch (error) {
    const status = error instanceof WebIdentityError ? error.status : 503;
    const detail = error instanceof Error ? error.message : "KJDS Web identity is unavailable";
    return Response.json({ detail }, { status });
  }

  const { path } = await context.params;
  const incoming = new URL(request.url);
  const target = new URL(path.map(encodeURIComponent).join("/"), `${apiBase.replace(/\/$/, "")}/`);
  target.search = incoming.search;

  const headers = new Headers();
  for (const name of forwardedRequestHeaders) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("x-kjds-api-key", apiKey);

  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  try {
    const upstream = await fetch(target, {
      method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
    });
    const responseHeaders = new Headers();
    for (const name of forwardedResponseHeaders) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    responseHeaders.set("cache-control", "no-store");
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch {
    return Response.json({ detail: "KJDS API is unavailable" }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
