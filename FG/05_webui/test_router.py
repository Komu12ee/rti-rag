from services.query_router import route_query
from services.retrieval_plan import Route


TEST_CASES = [
    # PostgreSQL: officer registry facts
    ("पकराड़ी स्कूल का PIO कौन है?", Route.POSTGRES),
    ("Who is the FAA for School Education Department in Balrampur?", Route.POSTGRES),
    ("Find officer using email rr1901138@gmail.com", Route.POSTGRES),
    ("बलरामपुर जिले के PIO का email दिखाइए", Route.POSTGRES),
    ("School Education Department के PIO की सूची दिखाओ", Route.POSTGRES),
    ("कार्यालय पुलिस अधीक्षक मुंगेली का FAA कौन है?", Route.POSTGRES),
    ("9220043429 office का PIO कौन है?", Route.POSTGRES),

    # Qdrant: law, procedure, precedent
    ("RTI Act में धारा 8(1)(j) क्या है?", Route.QDRANT),
    ("What are the duties of a PIO under the RTI Act?", Route.QDRANT),
    ("RTI आवेदन का जवाब कितने दिन में देना होता है?", Route.QDRANT),
    ("प्रथम अपील कैसे करें?", Route.QDRANT),
    ("CIC decision में record retention के बारे में क्या कहा गया है?", Route.QDRANT),
    ("PIO जवाब नहीं दे तो कानूनी रूप से क्या किया जा सकता है?", Route.QDRANT),

    # Hybrid: officer fact + legal guidance
    ("बलरामपुर के PIO का नाम और RTI reply की time limit बताओ", Route.HYBRID),
    (
        "Who is the FAA for this office and what can an applicant do if PIO does not reply?",
        Route.HYBRID,
    ),
    ("पकराड़ी स्कूल के PIO का email और प्रथम अपील की प्रक्रिया बताओ", Route.HYBRID),
    ("मुंगेली के FAA का नाम और RTI Act में उनकी भूमिका बताओ", Route.HYBRID),

    # Unclear: Router B should decide later
    ("मेरे स्कूल की RTI वाली जानकारी बताओ", Route.UNCLEAR),
    ("मुझे मदद चाहिए", Route.UNCLEAR),
    ("220260521007149 का status बताओ", Route.UNCLEAR),
]


def main() -> None:
    passed = 0

    print("\n" + "=" * 80)
    print("ROUTER A TEST RESULTS")
    print("=" * 80)

    for query, expected_route in TEST_CASES:
        decision = route_query(query)
        is_pass = decision.route == expected_route

        print(f"\nQuery:    {query}")
        print(f"Expected: {expected_route.value}")
        print(f"Actual:   {decision.route.value}")
        print(f"Reason:   {decision.reason}")
        print(f"Signals:  {list(decision.matched_signals)}")
        print(f"Result:   {'PASS' if is_pass else 'FAIL'}")

        if is_pass:
            passed += 1

    print("\n" + "=" * 80)
    print(f"Passed: {passed}/{len(TEST_CASES)}")
    print("=" * 80)

    if passed != len(TEST_CASES):
        raise SystemExit(1)


if __name__ == "__main__":
    main()