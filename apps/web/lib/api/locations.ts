"use client";

/**
 * Re-export of the locations client.
 *
 * The historical home of ``fetchLocations`` is ``lib/api/invites.ts``
 * because that's the screen that needed it first. As more screens (the
 * analytics location picker, the history filter) start consuming it, we
 * give it its own canonical module so a future reader doesn't have to
 * remember that "locations live under invites". The implementation is
 * deliberately kept in invites.ts to avoid two divergent definitions.
 */

export { fetchLocations, type LocationRow } from "@/lib/api/invites";
