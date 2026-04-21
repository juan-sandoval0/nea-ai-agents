/**
 * Clerk Authentication Middleware
 *
 * Phase 3.1: Protects routes that require authentication.
 *
 * This middleware:
 * - Protects all platform routes (/briefing, /outreach, /digest)
 * - Allows public access to the landing page (/)
 * - Redirects unauthenticated users to Clerk sign-in
 *
 * Note: Only active when @clerk/nextjs is installed and configured.
 */

import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Routes that require authentication
const isProtectedRoute = createRouteMatcher([
  "/briefing(.*)",
  "/outreach(.*)",
  "/digest(.*)",
  "/settings(.*)",
]);

// Routes that are always public
const isPublicRoute = createRouteMatcher([
  "/",
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/api/health",
]);

export default clerkMiddleware(async (auth, req) => {
  // Protect routes that require authentication
  if (isProtectedRoute(req) && !isPublicRoute(req)) {
    await auth.protect();
  }
});

export const config = {
  // Match all routes except static files and Next.js internals
  matcher: [
    // Skip Next.js internals and static files
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes
    "/(api|trpc)(.*)",
  ],
};
