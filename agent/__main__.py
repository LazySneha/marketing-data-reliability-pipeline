"""
Ask a question about one brand's marts.

    python -m agent --brand acme_apparel "What was revenue last week?"
    python -m agent --brand bloom_skin -v "Which SKUs are we spending on that are about to stock out?"

Every tool call is appended to agent/logs/transcript.jsonl.
"""
import argparse
import sys

import config
from agent.loop import ask


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--brand", required=True, choices=sorted(config.BRANDS),
                        help="the one tenant this session can see")
    parser.add_argument("-v", "--verbose", action="store_true", help="print each tool call as it happens")
    args = parser.parse_args()
    result = ask(args.question, args.brand, verbose=args.verbose)
    print(result["answer"])
    print(f"\n({result['turns']} turns, {len(result['tool_calls'])} tool calls)", file=sys.stderr)


if __name__ == "__main__":
    main()
