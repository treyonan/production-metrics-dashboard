"""
i3X API Test Script

Run this from the Ignition Script Console by calling:

    Integrations.i3X.test.main()

Workflow
--------
1. Call main() to run Section 1 (no-parameter functions) and confirm the
   HTTP framework, URL, and JSON parsing work correctly.
2. Copy ElementIds / subscriptionIds from the console output.
3. Paste them into the hardcoded values in Section 2, uncomment those
   blocks, and call main() again.
"""

from Integrations.i3X import API


# ============================================================================
# HELPERS
# ============================================================================

def _pass(name, detail=""):
    print("[PASS] {0}{1}".format(name, " -> " + str(detail) if detail else ""))

def _fail(name, err):
    print("[FAIL] {0} -> {1}".format(name, err))


# ============================================================================
# SECTION 1: NO-PARAMETER FUNCTIONS
# ============================================================================

def _section1():
    print("")
    print("=" * 60)
    print("SECTION 1 - No-Parameter Functions")
    print("=" * 60)

    # ── Explore ──────────────────────────────────────────────────────────────

    print("\n--- Explore ---")

    try:
        result = API.get_namespaces()
        _pass("get_namespaces()", "{0} namespace(s) returned".format(len(result)))
        for ns in result:
            print("    uri={0}  displayName={1}".format(ns.get("uri"), ns.get("displayName")))
    except Exception as e:
        _fail("get_namespaces()", e)

    try:
        result = API.get_object_types()
        _pass("get_object_types()", "{0} type(s) returned".format(len(result)))
    except Exception as e:
        _fail("get_object_types()", e)

    try:
        result = API.get_relationship_types()
        _pass("get_relationship_types()", "{0} type(s) returned".format(len(result)))
    except Exception as e:
        _fail("get_relationship_types()", e)

    try:
        result = API.get_objects()
        _pass("get_objects()", "{0} object(s) returned".format(len(result)))
    except Exception as e:
        _fail("get_objects()", e)

    # ── Subscribe ─────────────────────────────────────────────────────────────

    print("\n--- Subscribe ---")

    try:
        result = API.list_subscriptions()
        ids = result.get("subscriptionIds", [])
        _pass("list_subscriptions()", "{0} active subscription(s)".format(len(ids)))
    except Exception as e:
        _fail("list_subscriptions()", e)

    try:
        result = API.create_subscription()
        sub_id = result.get("subscriptionId", "?")
        _pass("create_subscription()", "subscriptionId={0}".format(sub_id))
        print("    NOTE: Copy subscriptionId above into SECTION 2 -> SUB_ID")
        print("    NOTE: Call API.delete_subscription('{0}') when done testing".format(sub_id))
    except Exception as e:
        _fail("create_subscription()", e)


# ============================================================================
# SECTION 2: PARAMETERIZED FUNCTIONS
#
# Instructions:
#   - Copy values from the Section 1 output into the variables below.
#   - Uncomment the block(s) you want to test.
#   - Call main() again.
# ============================================================================

def _section2():
    print("")
    print("=" * 60)
    print("SECTION 2 - Parameterized Functions")
    print("=" * 60)

    # ── Hardcoded test values ─────────────────────────────────────────────────
    # Paste real values from Section 1 output here before uncommenting blocks.

    # NAMESPACE_URI  = "urn:example:namespace"   # from get_namespaces() uri field
    # OBJ_TYPE_ID    = "urn:example:Pump"        # from get_object_types() elementId field
    # REL_TYPE_ID    = "urn:example:HasComp"     # from get_relationship_types() elementId field
    # OBJECT_ID      = "urn:example:Pump1"       # from get_objects() elementId field
    # SUB_ID         = "1"                       # from create_subscription() subscriptionId field
    # START_TIME     = "2024-01-01T00:00:00Z"    # ISO-8601
    # END_TIME       = "2024-01-02T00:00:00Z"    # ISO-8601
    # NEW_VALUE      = 0.0                       # value to write via update_value()


    # ── Explore (parameterized) ───────────────────────────────────────────────

    # print("\n--- Explore (parameterized) ---")

    # try:
    #     result = API.query_object_types([OBJ_TYPE_ID])
    #     _pass("query_object_types()", "{0} result(s)".format(len(result)))
    # except Exception as e:
    #     _fail("query_object_types()", e)

    # try:
    #     result = API.query_relationship_types([REL_TYPE_ID])
    #     _pass("query_relationship_types()", "{0} result(s)".format(len(result)))
    # except Exception as e:
    #     _fail("query_relationship_types()", e)

    # try:
    #     result = API.list_objects([OBJECT_ID])
    #     _pass("list_objects()", "{0} result(s)".format(len(result)))
    # except Exception as e:
    #     _fail("list_objects()", e)

    # try:
    #     result = API.get_related_objects([OBJECT_ID])
    #     _pass("get_related_objects()", "{0} result(s)".format(len(result)))
    # except Exception as e:
    #     _fail("get_related_objects()", e)


    # ── Query ─────────────────────────────────────────────────────────────────

    # print("\n--- Query ---")

    # try:
    #     result = API.get_values([OBJECT_ID])
    #     _pass("get_values()", result)
    # except Exception as e:
    #     _fail("get_values()", e)

    # try:
    #     result = API.get_history([OBJECT_ID], START_TIME, END_TIME)
    #     _pass("get_history()", result)
    # except Exception as e:
    #     _fail("get_history()", e)


    # ── Update ────────────────────────────────────────────────────────────────

    # print("\n--- Update ---")

    # try:
    #     result = API.update_value(OBJECT_ID, NEW_VALUE)
    #     _pass("update_value()", result)
    # except Exception as e:
    #     _fail("update_value()", e)


    # ── Subscribe (parameterized) ─────────────────────────────────────────────

    # print("\n--- Subscribe (parameterized) ---")

    # try:
    #     result = API.get_subscription(SUB_ID)
    #     _pass("get_subscription()", result)
    # except Exception as e:
    #     _fail("get_subscription()", e)

    # try:
    #     result = API.register_items(SUB_ID, [OBJECT_ID])
    #     _pass("register_items()", result)
    # except Exception as e:
    #     _fail("register_items()", e)

    # try:
    #     result = API.sync(SUB_ID)
    #     _pass("sync()", "{0} update(s)".format(len(result) if result else 0))
    # except Exception as e:
    #     _fail("sync()", e)

    # try:
    #     result = API.unregister_items(SUB_ID, [OBJECT_ID])
    #     _pass("unregister_items()", result)
    # except Exception as e:
    #     _fail("unregister_items()", e)

    # try:
    #     result = API.delete_subscription(SUB_ID)
    #     _pass("delete_subscription()", result)
    # except Exception as e:
    #     _fail("delete_subscription()", e)


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    _section1()
    _section2()
    print("")
    print("=" * 60)
    print("Done")
    print("=" * 60)
