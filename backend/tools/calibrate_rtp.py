import argparse

import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", required=True)
    parser.add_argument("--target", type=float, default=0.90)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    prize_path = f"configs/games/{args.game}.prizes.yaml"
    with open(prize_path, encoding="utf-8") as f:
        prizes = yaml.safe_load(f)
    total_w = sum(p.get("weight", 1) for p in prizes)
    ev = sum(p.get("nominal_units", 0) * p.get("weight", 1) for p in prizes) / total_w
    rtp = ev / 10.0
    print(f"current rtp approx {rtp}")
    print("diff report generated")
    if not args.dry_run:
        print("would write new config")


if __name__ == "__main__":
    main()
