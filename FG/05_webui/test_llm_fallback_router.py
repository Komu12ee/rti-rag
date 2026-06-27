from services.llm_fallback_router import classify_with_llm


TEST_QUERIES = [
    "मुझे RTI के बारे में कुछ बताओ",
    "बलरामपुर के स्कूल में RTI किसको भेजें और जवाब कितने दिन में मिलता है?",
    "सरकारी स्कूल का PIO contact details चाहिए",
    "RTI में first appeal कैसे करें?",
    "मुझे किसी office की जानकारी चाहिए",
]


def main() -> None:
    print("\n" + "=" * 95)
    print("ROUTER B — OLLAMA FALLBACK CLASSIFIER TEST")
    print("=" * 95)

    for query in TEST_QUERIES:
        decision = classify_with_llm(query)

        print(f"\nQuery: {query}")
        print(f"Route: {decision.route.value}")
        print(f"Confidence: {decision.confidence}")
        print(f"Reason: {decision.reason}")
        print(f"Signals: {decision.matched_signals}")

    print("\n" + "=" * 95)


if __name__ == "__main__":
    main()