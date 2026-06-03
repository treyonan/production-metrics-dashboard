// Shared site-id URL helpers.
//
// Three jobs:
//
//   1. parseSiteIdFromUrl()         -- read ?site_id= off the current URL
//   2. writeSiteIdToUrl(id)         -- update ?site_id= via replaceState
//   3. withSiteId(href, id)         -- rewrite an outbound href to include ?site_id=
//
// Used by app.js (main dashboard) and timebase-trends.js (Time Series
// page). Loaded as a plain <script> before the page-specific JS so the
// helpers attach to window.pmdSiteLink. Not an ES module on purpose --
// the rest of the frontend ships as classic scripts, no bundler.

(function () {
  "use strict";

  /** Return the ?site_id value off the current URL, or null. */
  function parseSiteIdFromUrl() {
    try {
      return new URLSearchParams(window.location.search).get("site_id");
    } catch (e) {
      return null;
    }
  }

  /**
   * Update the current URL's ?site_id= in place (no history entry).
   * Preserves every other query param. Silent no-op on browsers that
   * don't support replaceState -- deep-linking is a nicety, not
   * load-bearing.
   */
  function writeSiteIdToUrl(siteId) {
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("site_id", String(siteId));
      window.history.replaceState(null, "", url.toString());
    } catch (e) {
      // ignore
    }
  }

  /**
   * Return a new URL string with ?site_id=<id> set on it, leaving all
   * other query params alone. Used by topbar links so an operator
   * navigating between Dashboard / Time Series carries the current
   * site forward without having to re-deep-link.
   *
   * Accepts absolute URLs, relative URLs, and root-relative paths.
   * Returns the original href untouched when something goes wrong --
   * a broken link with the original href is better than a broken
   * link with no href.
   */
  function withSiteId(href, siteId) {
    if (!href || siteId === undefined || siteId === null) return href;
    try {
      const u = new URL(href, window.location.origin);
      u.searchParams.set("site_id", String(siteId));
      // Return root-relative when same-origin so the rewritten href
      // matches the static href shape ("/timebase-trends.html?site_id=100"
      // rather than "http://host:port/timebase-trends.html?site_id=100").
      if (u.origin === window.location.origin) {
        return u.pathname + u.search + u.hash;
      }
      return u.toString();
    } catch (e) {
      return href;
    }
  }

  window.pmdSiteLink = {
    parseSiteIdFromUrl: parseSiteIdFromUrl,
    writeSiteIdToUrl: writeSiteIdToUrl,
    withSiteId: withSiteId,
  };
})();
