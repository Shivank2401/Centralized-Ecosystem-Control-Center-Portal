"""
Country-specific pincode cleaning and City/State attachment from per-country CSV files.

CSV directory (same layout as pincode export scripts):
  .../Cron_files/code execution/pincode/
    us_amazon_pincode.csv, ca_amazon_pincode.csv, de_amazon_pincode.csv,
    uk_amazon_pincode.csv, in_amazon_pincode.csv, ae_amazon_pincode.csv,
    ie_amazon_pincode.csv

Used by knc_orders_processing.py (same logic as orders_processing.ipynb).
Shopify orders use `attach_shopify_city_state` (maps `pincode_new` → `pincode` then same lookup).
"""
from __future__ import annotations
import traceback

import os
import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config_manager import paths

PINCODE_CSV_FILES = {
    "US": "us_amazon_pincode.csv",
    "CA": "ca_amazon_pincode.csv",
    "DE": "de_amazon_pincode.csv",
    "UK": "uk_amazon_pincode.csv",
    "IN": "in_amazon_pincode.csv",
    "AE": "ae_amazon_pincode.csv",
    "IE": "ie_amazon_pincode.csv",
}


def get_pincode_data_dir() -> str:
    """Absolute path to pincode CSV folder (from .env or project `/pincode`)."""
    path = paths.pincode_data_dir()
    if not path.is_dir():
        raise FileNotFoundError(
            f"PINCODE_DATA_DIR is not a directory: {path}. "
            "Check .env PINCODE_DATA_DIR (quote paths that contain spaces)."
        )
    return str(path)


def __getattr__(name: str):
    if name == "PINCODE_DATA_DIR":
        return get_pincode_data_dir()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _pincode_csv_path(geo_key: str) -> str:
    fname = PINCODE_CSV_FILES[geo_key.upper()]
    return os.path.join(get_pincode_data_dir(), fname)


def _canonical_header(name: str) -> str:
    n = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    if n in ("pincode", "postal_code", "postcode", "zip", "zipcode"):
        return "Pincode"
    if n == "city":
        return "City"
    if n in ("state", "province", "region", "county"):
        return "State"
    if n == "country":
        return "Country"
    if n in ("ship_city", "shipcity"):
        return "ship-city"
    return str(name).strip()


def _read_pincode_csv(geo_key: str) -> pd.DataFrame:
    path = _pincode_csv_path(geo_key)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Pincode CSV not found: {path}")
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)
    df.columns = [_canonical_header(c) for c in df.columns]
    return df


def _ensure_cols(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = None
    return out


def _format_ca_pincode(pincode: Any) -> str:
    if pd.isna(pincode) or pincode == "nan" or not isinstance(pincode, str):
        return "NotAvailable"
    if len(pincode) > 3 and pincode[3] != " ":
        return pincode[:3] + " " + pincode[3:]
    return pincode


def attach_city_state_ca(orders_df: pd.DataFrame) -> pd.DataFrame:
    df = orders_df.copy()
    df["pincode"] = np.where(df["pincode"].isnull(), df["city"], df["pincode"])
    df["pincode_new"] = df["pincode"].astype(str).str.replace(" ", "", regex=False)
    df["pincode_new"] = df["pincode_new"].apply(_format_ca_pincode)

    ca_pincode = _ensure_cols(_read_pincode_csv("CA"), ["Pincode", "City", "State", "Country"]).drop_duplicates(
        subset=["Pincode"]
    )
    ca_pincode = ca_pincode.copy()
    ca_pincode["Pincode"] = ca_pincode["Pincode"].astype(str)
    lookup_dict: Dict[str, Dict[str, Any]] = ca_pincode.set_index("Pincode")[["City", "State"]].to_dict("index")

    df["pincode_new"] = df["pincode_new"].astype(str)

    def get_city_state(pin: str) -> Dict[str, Any]:
        return lookup_dict.get(pin, {"City": None, "State": None})

    df[["City", "State"]] = df["pincode_new"].apply(lambda x: pd.Series(get_city_state(x)))
    df = pd.merge(
        df,
        ca_pincode.loc[:, ["Pincode", "City", "State"]],
        how="left",
        left_on="pincode_new",
        right_on="Pincode",
    )
    df["City"] = np.where(df["City_x"].notnull(), df["City_x"], df["City_y"])
    df["State"] = np.where(df["State_x"].notnull(), df["State_x"], df["State_y"])
    df.drop(
        columns=["City_y", "State_y", "pincode", "city", "City_x", "State_x", "Pincode"],
        inplace=True,
        errors="ignore",
    )
    df["City"] = df["City"].fillna("Outside Canada")
    df["State"] = df["State"].fillna("Outside Canada")
    return df


def attach_city_state_de(orders_df: pd.DataFrame) -> pd.DataFrame:
    df = orders_df.copy()

    def normalize_de_pin(val: Any) -> Optional[str]:
        if pd.isna(val):
            return None
        s = str(val).strip()
        if s == "" or s.lower() in ("nan", "none"):
            return None
        digits = re.findall(r"\d+", s)
        if not digits:
            return None
        joined = "".join(digits)
        return joined[:5] if len(joined) >= 1 else None

    df["pincode_new"] = df["pincode"].apply(normalize_de_pin)

    de_pin_df = _ensure_cols(_read_pincode_csv("DE"), ["Pincode", "City", "State"]).drop_duplicates()
    de_pin_df["Pincode_norm"] = de_pin_df["Pincode"].astype(str).apply(
        lambda x: re.sub(r"\D", "", x).strip()[:5] if pd.notna(x) and re.search(r"\d", str(x)) else None
    )
    de_pin_df = de_pin_df[de_pin_df["Pincode_norm"].notna()]
    de_unique = de_pin_df.drop_duplicates(subset=["Pincode_norm"]).copy()
    lookup_full = de_unique.set_index("Pincode_norm")[["City", "State"]].to_dict("index")
    de_unique["prefix3"] = de_unique["Pincode_norm"].str[:3]
    prefix3_map = (
        de_unique.dropna(subset=["prefix3"])
        .drop_duplicates(subset=["prefix3"])
        .set_index("prefix3")[["City", "State"]]
        .to_dict("index")
    )

    def lookup_city_state(pin: Optional[str]) -> Dict[str, Any]:
        if pin is None:
            return {"City": None, "State": None}
        res = lookup_full.get(pin)
        if res:
            return res
        pref = pin[:3] if len(pin) >= 3 else None
        if pref:
            res2 = prefix3_map.get(pref)
            if res2:
                return res2
        return {"City": None, "State": None}

    df[["City", "State"]] = df["pincode_new"].apply(lambda x: pd.Series(lookup_city_state(x)))
    df["City"] = np.where(df["City"].notnull(), df["City"], df["city"])
    df["State"] = df["State"].fillna("Not Available")
    df["City"] = df["City"].fillna("Outside DE")
    df["State"] = df["State"].fillna("Outside DE")
    df.drop(columns=["city", "pincode"], inplace=True, errors="ignore")
    return df


def _replace_alpha_with_zero(pincode: Any) -> Any:
    if isinstance(pincode, str) and len(pincode) > 0 and pincode[0].isalpha():
        return 0
    return pincode


def attach_city_state_in(orders_df: pd.DataFrame) -> pd.DataFrame:
    df = orders_df.copy()
    df["pincode"] = np.where(df["pincode"].isnull(), df["city"], df["pincode"])
    df["pincode_new"] = df["pincode"].astype(str).str.replace(" ", "", regex=False)
    df["pincode_new"] = df["pincode_new"].apply(lambda x: str(x).split("-")[0])
    df["pincode_new"] = df["pincode_new"].apply(lambda x: str(x).split(" ")[0])
    df["pincode_new"] = df["pincode_new"].str.replace("....", "0", regex=False)
    df["pincode_new"] = df["pincode_new"].fillna(0)
    df["pincode_new"] = df["pincode_new"].apply(_replace_alpha_with_zero)
    df["pincode_new"] = df["pincode_new"].fillna("NotAvailable")

    india_pincode = _ensure_cols(_read_pincode_csv("IN"), ["Pincode", "City", "State", "Country"]).drop_duplicates(
        subset=["Pincode"]
    )
    india_pincode["Pincode"] = india_pincode["Pincode"].astype(str)
    lookup_dict = india_pincode.set_index("Pincode")[["City", "State"]].to_dict("index")
    df["pincode_new"] = df["pincode_new"].astype(str)

    def get_city_state(pin: str) -> Dict[str, Any]:
        return lookup_dict.get(pin, {"City": None, "State": None})

    df[["City", "State"]] = df["pincode_new"].apply(lambda x: pd.Series(get_city_state(x)))
    df = pd.merge(
        df,
        india_pincode.loc[:, ["Pincode", "City", "State"]],
        how="left",
        left_on="pincode_new",
        right_on="Pincode",
    )
    df["City"] = np.where(df["City_x"].notnull(), df["City_x"], df["City_y"])
    df["State"] = np.where(df["State_x"].notnull(), df["State_x"], df["State_y"])
    df.drop(
        columns=["City_y", "State_y", "pincode", "city", "City_x", "State_x", "Pincode"],
        inplace=True,
        errors="ignore",
    )
    df["City"] = df["City"].fillna("Outside India")
    df["State"] = df["State"].fillna("Outside India")
    return df


def attach_city_state_ae(orders_df: pd.DataFrame) -> pd.DataFrame:
    df = orders_df.copy()
    df["pincode"] = np.where(df["pincode"].isnull(), df["city"], df["pincode"])
    df["pincode_new"] = df["pincode"].astype(str).str.replace(" ", "", regex=False)
    df["pincode_new"] = df["pincode_new"].apply(lambda x: str(x).split("-")[0])
    df["pincode_new"] = df["pincode_new"].apply(lambda x: str(x).split(" ")[0])
    df["pincode_new"] = df["pincode_new"].fillna("NotAvailable")
    df["city"] = df["city"].fillna("Outside UAE").astype(str).str.strip().str.title()

    uae_pincode = _read_pincode_csv("AE")
    uae_pincode.columns = [str(c).strip() for c in uae_pincode.columns]
    ship_col = None
    for c in uae_pincode.columns:
        norm = c.lower().replace("_", "-").replace(" ", "-")
        if norm in ("ship-city", "shipcity"):
            ship_col = c
            break
    if ship_col is None:
        raise ValueError("UAE pincode sheet: expected a ship-city (or ship city) column.")

    right = uae_pincode[[ship_col, "City", "State"]].copy()
    right = right.rename(columns={ship_col: "_ship_city_match"})
    df = df.merge(right, how="left", left_on="city", right_on="_ship_city_match")
    df.drop(columns=["_ship_city_match", "pincode", "city"], inplace=True, errors="ignore")
    df["City"] = df["City"].fillna("Outside UAE")
    df["State"] = df["State"].fillna("Outside UAE")
    return df


def _uk_split_outward(pincode: Any) -> str:
    match = re.match(r"([A-Za-z]{1,2}\d{1,2}[A-Za-z]?)", str(pincode))
    if match:
        return match.group(1).upper()
    return str(pincode).upper()


def _attach_city_state_uk_style(orders_df: pd.DataFrame, geo_key: str, outside_label: str) -> pd.DataFrame:
    """UK / Ireland: same outward-code and multi-step lookup logic; data from per-geo CSV."""
    df = orders_df.copy()
    df["pincode_new"] = df["pincode"].astype(str).str.replace(" ", "", regex=False)
    df["pincode_new"] = df["pincode_new"].fillna("NotAvailable")
    df["Pincode 1"] = df["pincode_new"].apply(_uk_split_outward)
    df["Pincode 0"] = df.apply(
        lambda row: str(row["pincode_new"])[:3].upper() if row["pincode_new"] else row["pincode_new"], axis=1
    )

    pincode_master = _ensure_cols(_read_pincode_csv(geo_key), ["Pincode", "City", "State", "Country"])
    pincode_master = pincode_master.assign(Pincode=pincode_master["Pincode"].astype(str).str.split(", ")).explode(
        "Pincode"
    )
    pincode_master = pincode_master.drop_duplicates(subset=["Pincode"])
    pincode_master["Pincode"] = pincode_master["Pincode"].astype(str)
    lookup_dict = pincode_master.set_index("Pincode")[["City", "State"]].to_dict("index")

    def get_city_state(pin: str) -> Dict[str, Any]:
        return lookup_dict.get(pin, {"City": None, "State": None})

    df["Pincode 1"] = df["Pincode 1"].astype(str)
    df[["City", "State"]] = df["Pincode 1"].apply(lambda x: pd.Series(get_city_state(x)))

    def first_4(pin: str) -> str:
        return str(pin)[:4].upper() if pin else pin

    def _need_pincode2(row: pd.Series) -> str:
        c_ok = pd.notna(row["City"]) and str(row["City"]).strip() != ""
        s_ok = pd.notna(row["State"]) and str(row["State"]).strip() != ""
        if c_ok or s_ok:
            return ""
        return first_4(row["pincode_new"])

    df["Pincode 2"] = df.apply(_need_pincode2, axis=1)
    df["Pincode 2"] = df["Pincode 2"].astype(str)
    df[["City2", "State2"]] = df["Pincode 2"].apply(lambda x: pd.Series(get_city_state(x)))
    df["Pincode 0"] = df["Pincode 0"].astype(str)
    df[["City3", "State3"]] = df["Pincode 0"].apply(lambda x: pd.Series(get_city_state(x)))

    df["City"] = np.where(
        df["City"].notnull(),
        df["City"],
        np.where(df["City2"].notnull(), df["City2"], df["City3"]),
    )
    df["State"] = np.where(
        df["State"].notnull(),
        df["State"],
        np.where(df["State2"].notnull(), df["State2"], df["State3"]),
    )
    df = pd.merge(
        df,
        pincode_master.loc[:, ["Pincode", "City", "State"]],
        how="left",
        left_on="pincode_new",
        right_on="Pincode",
    )
    df["City"] = np.where(df["City_x"].notnull(), df["City_x"], df["City_y"])
    df["State"] = np.where(df["State_x"].notnull(), df["State_x"], df["State_y"])
    df.drop(
        columns=[
            "City2",
            "State2",
            "City3",
            "State3",
            "Pincode 2",
            "Pincode 1",
            "Pincode 0",
            "City_y",
            "State_y",
            "pincode",
            "city",
            "City_x",
            "State_x",
            "Pincode",
        ],
        inplace=True,
        errors="ignore",
    )
    df["City"] = df["City"].fillna(outside_label)
    df["State"] = df["State"].fillna(outside_label)
    return df


def attach_city_state_uk(orders_df: pd.DataFrame) -> pd.DataFrame:
    return _attach_city_state_uk_style(orders_df, "UK", "Outside UK")


def attach_city_state_ie(orders_df: pd.DataFrame) -> pd.DataFrame:
    return _attach_city_state_uk_style(orders_df, "IE", "Outside IE")


def attach_city_state_us(orders_df: pd.DataFrame) -> pd.DataFrame:
    df = orders_df.copy()
    df["pincode"] = np.where(df["pincode"].isnull(), df["city"], df["pincode"])
    df["pincode_new"] = df["pincode"].astype(str).str.replace(" ", "", regex=False)
    df["pincode_new"] = df["pincode_new"].apply(lambda x: str(x).split("-")[0])
    df["pincode_new"] = df["pincode_new"].apply(lambda x: str(x).split(" ")[0])
    df["pincode_new"] = df["pincode_new"].str.replace("....", "0", regex=False)
    df["pincode_new"] = df["pincode_new"].fillna(0)
    df["pincode_new"] = df["pincode_new"].apply(_replace_alpha_with_zero)
    df["pincode_new"] = df["pincode_new"].fillna("NotAvailable")

    pincode_df = _ensure_cols(_read_pincode_csv("US"), ["Pincode", "City", "State", "Country"]).drop_duplicates(
        subset=["Pincode"]
    )
    pincode_df["Pincode"] = pincode_df["Pincode"].astype(str)
    lookup_dict = pincode_df.set_index("Pincode")[["City", "State"]].to_dict("index")
    df["pincode_new"] = df["pincode_new"].astype(str)

    def get_city_state(pin: str) -> Dict[str, Any]:
        return lookup_dict.get(pin, {"City": None, "State": None})

    df[["City", "State"]] = df["pincode_new"].apply(lambda x: pd.Series(get_city_state(x)))
    df = pd.merge(
        df,
        pincode_df.loc[:, ["Pincode", "City", "State"]],
        how="left",
        left_on="pincode_new",
        right_on="Pincode",
    )
    df["City"] = np.where(df["City_x"].notnull(), df["City_x"], df["City_y"])
    df["State"] = np.where(df["State_x"].notnull(), df["State_x"], df["State_y"])
    df.drop(
        columns=["City_y", "State_y", "Pincode", "pincode", "City_x", "State_x", "city"],
        inplace=True,
        errors="ignore",
    )
    df["City"] = df["City"].fillna("Outside USA")
    df["State"] = df["State"].fillna("Outside USA")
    return df


def attach_shopify_city_state(geo_code: str, orders_df: pd.DataFrame) -> pd.DataFrame:
    """
    Shopify exports use `pincode_new` / `city`; normalize to `pincode` / `city` for UK/IE lookup.
    """
    df = orders_df.copy()
    if "pincode" not in df.columns and "pincode_new" in df.columns:
        df = df.rename(columns={"pincode_new": "pincode"})
    if "city" not in df.columns and "City" in df.columns:
        df = df.rename(columns={"City": "city"})
    return attach_city_state_for_geo(geo_code, df)


def attach_city_state_for_geo(geo_code: str, orders_df: pd.DataFrame) -> pd.DataFrame:
    code = geo_code.upper()
    if code == "CA":
        return attach_city_state_ca(orders_df)
    if code == "DE":
        return attach_city_state_de(orders_df)
    if code == "IN":
        return attach_city_state_in(orders_df)
    if code == "AE":
        return attach_city_state_ae(orders_df)
    if code == "UK":
        return attach_city_state_uk(orders_df)
    if code == "US":
        return attach_city_state_us(orders_df)
    if code == "IE":
        return attach_city_state_ie(orders_df)
    raise ValueError(f"Unsupported geo for pincode processing: {geo_code}")
