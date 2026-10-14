from __future__ import annotations
import sys
import numpy as np
from rxnfp.transformer_fingerprints import RXNBERTFingerprintGenerator, get_default_model_and_tokenizer

def main() -> int:
    if len(sys.argv) != 3:
        return 2
    reactions = [x for x in open(sys.argv[1], encoding="utf-8").read().splitlines() if x]
    model, tokenizer = get_default_model_and_tokenizer(model="bert_ft", force_no_cuda=True)
    generator = RXNBERTFingerprintGenerator(model, tokenizer, force_no_cuda=True)
    arr = np.asarray(generator.convert_batch(reactions), dtype=np.float32)
    np.save(sys.argv[2], arr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
