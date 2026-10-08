import { toNextJsHandler } from "better-auth/next-js";

import { AuthNotConfiguredError, getAuth } from "../../../../lib/auth";
import { withEmailDeliveryStatus } from "../../../../lib/email-otp";

function createHandler(method: "GET" | "POST") {
  return async (request: Request): Promise<Response> => {
    try {
      const handlers = toNextJsHandler(getAuth());
      return await withEmailDeliveryStatus(() => handlers[method](request));
    } catch (error) {
      if (error instanceof AuthNotConfiguredError) {
        return Response.json({ error: "Authentication is not configured" }, { status: 503 });
      }
      throw error;
    }
  };
}

export const GET = createHandler("GET");
export const POST = createHandler("POST");
