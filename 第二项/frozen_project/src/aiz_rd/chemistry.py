from __future__ import annotations

import hashlib

from rdkit import Chem


class ChemistryStandardizationError(ValueError):
    pass


def canonicalize_molecule_smiles(smiles: str, context: str = "molecule") -> str:
    if not isinstance(smiles, str) or not smiles.strip():
        raise ChemistryStandardizationError(f"Empty/non-string SMILES in {context}: {smiles!r}")
    try:
        mol = Chem.MolFromSmiles(smiles, sanitize=True)
    except Exception as exc:
        raise ChemistryStandardizationError(f"RDKit parse/sanitize failed in {context}: {smiles!r}: {exc}") from exc
    if mol is None:
        raise ChemistryStandardizationError(f"RDKit parse/sanitize failed in {context}: {smiles!r}")
    mol = Chem.Mol(mol)
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)


def canonicalize_precursors(precursors: list[str] | tuple[str, ...]) -> str:
    if not precursors:
        raise ChemistryStandardizationError("Reaction contains no precursors")
    canonical = [canonicalize_molecule_smiles(item, f"precursor[{idx}]") for idx, item in enumerate(precursors)]
    return ".".join(sorted(canonical))


def canonicalize_reaction(precursors: list[str] | tuple[str, ...], product: str) -> tuple[str, str, str]:
    precursor_smiles = canonicalize_precursors(precursors)
    product_smiles = canonicalize_molecule_smiles(product, "product")
    reaction_smiles = f"{precursor_smiles}>>{product_smiles}"
    return precursor_smiles, product_smiles, reaction_smiles


def reaction_hash(reaction_smiles: str) -> str:
    if reaction_smiles.count(">>") != 1:
        raise ChemistryStandardizationError(f"Invalid canonical reaction SMILES: {reaction_smiles!r}")
    return hashlib.sha256(reaction_smiles.encode("utf-8")).hexdigest()
