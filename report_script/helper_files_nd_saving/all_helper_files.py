"""
ESH supply-chain script converted from notebook.
Processing logic preserved; SKU helpers use config_manager.esh_sku_cleaning.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager.esh_sku_cleaning import (
    clean_warehouse_sku_column,
    mapping_from_convertor_helper,
)
from config_manager import paths as cfg_paths




def main():
    """Converted notebook body (processing logic unchanged)."""
    # --- path roots from .env (no hardcoded OneDrive users) ---
    INV = cfg_paths.esh_inventory_root()
    CENTRAL = cfg_paths.esh_central_root()
    DEMAND_ROOT = cfg_paths.esh_demand_instock_root()  # optional

    # --- notebook cell 0 ---
    import pandas as pd
    import os
    import numpy as np
    import xlsxwriter
    import xlrd
    import re

    # --- notebook cell 1 ---
    from datetime import datetime
    from datetime import timedelta
    datestr_1 = (pd.to_datetime("today") - timedelta(1)).strftime("%d-%b-%Y")
    print(datestr_1)

    # --- notebook cell 2 ---
    from datetime import datetime
    datestr_2= (pd.to_datetime("today") - timedelta(2)).strftime("%d-%b-%Y")
    print(datestr_2)

    # --- notebook cell 3 ---
    datestr_2= (pd.to_datetime("today") - timedelta(2)).strftime("%d-%b-%Y")

    # --- notebook cell 4 ---
    from datetime import datetime
    from datetime import timedelta
    datestr_T = pd.to_datetime("today").strftime("%d-%b-%Y")
    print(datestr_T)

    # --- notebook cell 6 ---
    active = pd.read_excel(INV / r"us/input/shipbob/active.xlsx")
    inactive = pd.read_excel(INV / r"us/input/shipbob/inactive.xlsx")
    bundle = pd.read_excel(INV / r"us/input/shipbob/bundle.xlsx")

    # --- notebook cell 7 ---
    # active.to_excel(INV / r"us/input/shipbob/products_active/2024/feb/active_"+datestr_1+".xlsx",index = False)
    # inactive.to_excel(INV / r"us/input/shipbob/products_inactive/2024/feb/inactive_"+datestr_1+".xlsx",index = False)
    # bundle.to_excel(INV / r"us/input/shipbob/products_bundle/2024/feb/bundle_"+datestr_1+".xlsx",index = False)
    # bundle.to_excel(CENTRAL / r"Task file/Shipbob Bundles/Bundle.xlsx",index = False)

    active.to_excel(INV / rf"us\input\shipbob\products_active\2024\feb\active_{datestr_1}.xlsx", index=False)
    inactive.to_excel(INV / rf"us\input\shipbob\products_inactive\2024\feb\inactive_{datestr_1}.xlsx", index=False)
    bundle.to_excel(INV / rf"us\input\shipbob\products_bundle\2024\feb\bundle_{datestr_1}.xlsx", index=False)

    # --- notebook cell 10 ---
    item_master_main = pd.read_excel(CENTRAL / r"retail/us/input/item_master_data/item_details_master_sheet.xlsx")
    item_master_main.columns

    # --- notebook cell 11 ---
    item_master = item_master_main.loc[:,['sku',"sku_other_names",'Material','Product_Category',"Channel",
                                      'Product_Sub_Category', 'Product_Type','Units_Per_Set', 'Case_Pack_Qty','Product Category type','Parent','Main_WAC']]

    item_master.rename(columns= {'sku' : 'SKU'},inplace= True)
    item_master.head()

    # --- notebook cell 13 ---
    # Split the 'sku_other_names' column into up to 5 parts
    item_master[['ON_1', 'ON_2', 'ON_3', 'ON_4', 'ON_5']] = (
        item_master['sku_other_names']
        .str.split(r',\s*', expand=True, n=4)  # split into max 5 parts (n=4 gives 5 parts)
    )

    # Strip spaces
    item_master[['ON_1', 'ON_2', 'ON_3', 'ON_4', 'ON_5']] = (
        item_master[['ON_1', 'ON_2', 'ON_3', 'ON_4', 'ON_5']]
        .apply(lambda x: x.str.strip())
    )
    convertor_helper = item_master.loc[:, ["SKU", "ON_1", "ON_2", "ON_3", "ON_4", "ON_5"]]

    # --- notebook cell 15 ---
    convertor_helper

    # --- notebook cell 16 ---
    convertor = item_master_main.loc[:,['sku','Material','Product_Category','Product_Sub_Category', 'Product_Type','Units_Per_Set', 'Case_Pack_Qty','Product Category type','Main_WAC','Channel',]]
    convertor.rename(columns= {'sku' : 'SKU'},inplace= True)

    convertor['Main_WAC'] = convertor.Main_WAC.fillna(1)
    #convertor = pd.merge(convertor, COGS_required, on= 'SKU', how='left')

    convertor.head(2)

    # --- notebook cell 18 ---
    RMC = item_master_main.loc[:,['sku','Parent','Product Category type']] 
    RMC.head()

    # --- notebook cell 20 ---
    Combo_WAC = pd.read_excel(CENTRAL / r"retail/us/input/item_master_data/item_details_master_sheet.xlsx",sheet_name='Combo_WAC')

    Combo_WAC = Combo_WAC.loc[:,['sku','Parent','Product Type']] 

    Combo_WAC.head()

    # --- notebook cell 22 ---
    Base_WAC = RMC.drop(RMC[RMC['Product Category type']!= "Base"].index)

    Base_WAC.head()

    # --- notebook cell 23 ---
    Raw_material_convertor = pd.concat([Base_WAC, Combo_WAC], axis=0)
    Raw_material_convertor.head()

    # --- notebook cell 25 ---
    use_col_read = ["Container No. (Internal)","Container/ Tracking number (External)","Estimated Dispatched Date from Warehouse","Estimated Departure Date from Port",
                                 "Estimated Arrival Date on Port","Transit Time","WH_Arrival_Month","Origin Port","Destination Port","US WH Name","Delivered to WH Date","Reflecting in WH Inventory",
                                 "Status","New Container No","Delivery Type", "SUPPLIER NAME", "invoice_ No_1", ]
    container = pd.read_excel(CENTRAL / r"logistics/Container Data.xlsx",sheet_name="Container Tracking", usecols=use_col_read)

    # --- notebook cell 26 ---
    container = container.loc[:,["Container No. (Internal)","Container/ Tracking number (External)","Estimated Dispatched Date from Warehouse","Estimated Departure Date from Port",
                                 "Estimated Arrival Date on Port","Transit Time","WH_Arrival_Month","Origin Port","Destination Port","US WH Name","Delivered to WH Date","Reflecting in WH Inventory",
                                 "Status","New Container No","Delivery Type", "SUPPLIER NAME", "invoice_ No_1", ]]
    # Drop rows where all values are blank (NaN)
    container = container.dropna(how='all')
    container

    # --- notebook cell 28 ---
    use_sku_col = ['Container No. (Internal)', 'SKU','Location', 'Cases','Box/Cases', 'QTY in Box', 'Unit price/box', 'Commission per box','Type', 'Total price /box',
                                         'Total Amount /SKU (Inclusive Commission)','ETA Port']

    container_sku = pd.read_excel(CENTRAL / r"logistics/Container Data.xlsx",sheet_name="Container Content_SKU level",usecols=use_sku_col)
    container_sku.head()

    # --- notebook cell 30 ---
    required_col = ['Container No. (Internal)', 'SKU', 'Description', 'Location', 'Cases',
           'Box/Cases', 'QTY in Box', 'Unit price/box INR', 'Total price /box',
           'ETA',]

    container_sku_jk_global = pd.read_excel(CENTRAL / r"logistics/Container Data.xlsx",
    sheet_name="JK Global", usecols=required_col)
    container_sku_jk_global.head()

    # --- notebook cell 32 ---
    container_sku = pd.concat([container_sku, container_sku_jk_global],ignore_index=True,    sort=False)

    # --- notebook cell 33 ---
    container_sku = container_sku.loc[:,['Container No. (Internal)', 'SKU','Location', 'Cases','Box/Cases', 'QTY in Box', 'Unit price/box', 'Commission per box','Type', 'Total price /box',
                                         'Total Amount /SKU (Inclusive Commission)','ETA Port']] 
    container_sku = pd.merge(container_sku, container, on = 'Container No. (Internal)', how = "left")
    container_sku

    # --- notebook cell 34 ---

    container_sku.rename(
        columns={
            'Container No. (Internal)': 'Main_Container No.',
            'New Container No': 'Container No. (Internal)'
        },
        inplace=True
    )

    # ==========================================================
    # ADD STANDARD COLUMNS
    # ==========================================================

    container_sku["Status_Main"] = np.where(
        ((container_sku.Status != "AW") &
         (container_sku["Reflecting in WH Inventory"] == "Yes")),
        "Reached",

        np.where(
            ((container_sku.Status != "AW") &
             (container_sku["Reflecting in WH Inventory"] == "No")),
            "Reached but Not Received in Inventory",

            np.where(
                ((container_sku.Status == "AW") &
                 (container_sku["Reflecting in WH Inventory"] == "No")),
                "Awaited",
                "Reached but Not Received in Inventory"
            )
        )
    )

    India = [
        'NHAVA SHEVA',
        'IGI DELHI AIRPORT',
        'CHENNAI',
        'NHAVASHEVA',
        'Noida India',
        'Banglore'
    ]

    Vietnam = ['HAI PHONG, VIETNAM']

    container_sku["Origin"] = np.where(
        container_sku["Origin Port"].isin(India),
        "India",
        np.where(
            container_sku["Origin Port"].isin(Vietnam),
            "Vietnam",
            "China"
        )
    )

    container_sku["Main Delivery Date"] = np.where(
        container_sku.Status_Main == "Awaited",
        container_sku['Estimated Arrival Date on Port'],
        container_sku["Status"]
    )

    # ==========================================================
    # SELECT COLUMNS
    # ==========================================================

    container_sku = container_sku.loc[:, [
        'Container No. (Internal)',
        'Container/ Tracking number (External)',
        'SKU',
        'Cases',
        'Box/Cases',
        'QTY in Box',
        'Unit price/box',
        'Commission per box',
        'Total price /box',
        'Total Amount /SKU (Inclusive Commission)',
        'ETA Port',
        'Estimated Dispatched Date from Warehouse',
        'Estimated Departure Date from Port',
        'Estimated Arrival Date on Port',
        'Transit Time',
        'WH_Arrival_Month',
        'Origin',
        'Destination Port',
        'US WH Name',
        'Main Delivery Date',
        'Status_Main',
        'Reflecting in WH Inventory',
        'Main_Container No.',
        "Delivery Type",
        'Location',
        'Type',
        'SUPPLIER NAME',
        'invoice_ No_1',
        
    ]]

    container_sku.rename(
        columns={
            'Container No. (Internal)': "Container_No",
            'Container/ Tracking number (External)': 'Reference_No',
            'ETA Port': 'ETA Warehouse',
            'Estimated Dispatched Date from Warehouse': 'Dispatched Date from WH',
            'Estimated Departure Date from Port': "Departure Date from Port",
            'Estimated Arrival Date on Port': "Arrival Date on Port",
            'Status_Main': 'Status'
        },
        inplace=True
    )

    # ==========================================================
    # CLEAN HELPER + MAP CONTAINER SKUs (esh_sku_cleaning)
    # ==========================================================

    convertor_helper = convertor_helper.copy()
    convertor_helper.columns = convertor_helper.columns.astype(str).str.strip()
    convertor_helper = convertor_helper.replace(r'^\s*$', np.nan, regex=True)
    convertor_helper["SKU"] = convertor_helper["SKU"].astype(str).str.strip()
    convertor_helper = convertor_helper[
        convertor_helper["SKU"].notna()
        & (convertor_helper["SKU"] != "")
        & (convertor_helper["SKU"].str.lower() != "nan")
    ]

    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    container_sku = clean_warehouse_sku_column(
        container_sku, sku_column="SKU", sku_mapping=sku_mapping
    )

    # ==========================================================
    # DROP UNWANTED COLUMNS
    # ==========================================================

    container_sku.drop(
        columns=[
            'SUPPLIER NAME',
            'invoice_ No_1',
            
        ],
        inplace=True
    )

    # ==========================================================
    # FILL CONTAINER NUMBER
    # ==========================================================

    container_sku["Container_No"] = np.where(
        container_sku["Container_No"].isna(),
        container_sku["Main_Container No."],
        container_sku["Container_No"]
    )

    # ==========================================================
    # FINAL OUTPUT
    # ==========================================================

    container_sku

    # --- notebook cell 35 ---
    vendor_container = container.loc[:,["Container No. (Internal)", "SUPPLIER NAME", "invoice_ No_1", ]]
    vendor_container.head()

    # --- notebook cell 36 ---
    container_sku = pd.merge(container_sku,vendor_container, left_on ="Main_Container No.", right_on = "Container No. (Internal)", how = "left")
    container_sku.drop(columns = ["Container No. (Internal)"], inplace = True)
    container_sku.head(2)

    # --- notebook cell 37 ---
    # Apply the lambda function to convert dates
    container_sku['Main Delivery Date'] = container_sku['Main Delivery Date'].apply(
        lambda x: pd.to_datetime(x).strftime("%d-%b-%Y") if x is not None and pd.to_datetime(x, errors='coerce') is not pd.NaT else None)

    # --- notebook cell 38 ---
    import pandas as pd
    import numpy as np
    from datetime import datetime


    # Convert 'Month_year' to datetime format for month calculations
    container_sku['Month_Year'] = pd.to_datetime(container_sku['Main Delivery Date'], format='%d-%b-%Y', errors='coerce')


    # Define the reference month (e.g., current month)
    reference_date = datetime.now().replace(day=1)

    # Calculate difference in months
    container_sku['Month_diff'] = ((reference_date.year - container_sku['Month_Year'].dt.year) * 12 +
                        (reference_date.month - container_sku['Month_Year'].dt.month))

    # Define conditions and choices for the 'Days' categories
    conditions = [
        (container_sku['Month_diff'] == 1),                     # Previous month
        (container_sku['Month_diff'] == 2),                     # 2 months ago
        (container_sku['Month_diff'] == 3),                     # 3 months ago
        (container_sku['Month_diff'] == 4),                     # 4 months ago
        (container_sku['Month_diff'] == 5)                       # More than 120 days
    ]
    choices = ['0-30 days', '31-60 days', '61-90 days', '91-120 days', 'More than 120 days']

    # Apply the conditions to create a new 'Days' column
    container_sku['Aging'] = np.select(conditions, choices, default='Unknown')

    container_sku.tail(2)

    # --- notebook cell 39 ---
    container.rename(
        columns={
            "Container/ Tracking number (External)": "Reference_No"
        },
        inplace=True
    )

    # --- notebook cell 40 ---
    container_price = pd.pivot_table(container_sku, index = "Reference_No",values = "Total Amount /SKU (Inclusive Commission)", aggfunc = np.sum).reset_index()

    container = pd.merge(container, container_price, on = "Reference_No", how = "left")

    # --- notebook cell 42 ---
    with pd.ExcelWriter(INV / r"IMS_new_Dashboard_files/Container_Data.xlsx") as writer:
        container.to_excel(writer, sheet_name = "Container", index = False)
        container_sku.to_excel(writer, sheet_name = "Container SKU", index = False)

    # --- notebook cell 44 ---
    max_SKU_box_case = container_sku.loc[:,["Container_No","SKU", "Box/Cases"]]
    max_SKU_box_case = max_SKU_box_case.pivot_table(index= 'SKU',columns= 'Container_No' , values=['Box/Cases'], aggfunc='sum').reset_index()
    max_SKU_box_case = max_SKU_box_case.fillna(0)
    max_SKU_box_case.head()

    # --- notebook cell 45 ---
    # Drop the first level of the header
    max_SKU_box_case.columns = max_SKU_box_case.columns.droplevel(0)

    # Rename the remaining header levels if needed
    max_SKU_box_case.columns.names = [None] * len(max_SKU_box_case.columns.names) # type: ignore

    # Get the current column names
    current_columns = list(max_SKU_box_case.columns)

    # Replace blank headers with new names
    new_columns = ['SKU' if col == '' else col for col in current_columns]

    # Update the DataFrame with the new column names
    max_SKU_box_case.columns = new_columns

    # Display the DataFrame after dropping the first level of the header
    max_SKU_box_case.head()

    # --- notebook cell 46 ---
    # Extract numerical columns for finding the maximum along each row
    numerical_columns = max_SKU_box_case.columns.difference(['SKU'])

    # Add a new column 'Max' with the maximum value for each row
    max_SKU_box_case['Max'] = max_SKU_box_case[numerical_columns].max(axis=1)

    # Get column names
    columns = list(max_SKU_box_case.columns)

    # Arrange columns with "SKU", "Max", and then remaining columns
    arranged_columns = ['SKU', 'Max'] + [col for col in columns if col not in ['SKU', 'Max']]

    # Create a new DataFrame with arranged columns
    max_SKU_box_case = max_SKU_box_case[arranged_columns]

    # Display the arranged DataF
    compare = max_SKU_box_case.loc[:,["SKU", "Max"]]
    max_SKU_box_case.head()

    # --- notebook cell 48 ---
    wac = container_sku.drop(container_sku[container_sku.Status != "Reached" ].index)
    wac = wac.loc[:,["SKU","QTY in Box", "Total Amount /SKU (Inclusive Commission)" ]]

    wac = wac.pivot_table(index= 'SKU', values=['QTY in Box', 'Total Amount /SKU (Inclusive Commission)'], aggfunc='sum').reset_index()

    wac["WAC"] = wac['Total Amount /SKU (Inclusive Commission)'] / wac['QTY in Box']

    wac.to_excel(INV / r"dashboard_essential_files/Addon Files/Container_WAC.xlsx")
    wac.head()

    # --- notebook cell 50 ---
    convertor_main = pd.merge(pd.merge(convertor_helper, convertor, on = "SKU", how= "left"),compare, on = "SKU", how= "left")

    convertor_main["Case_Pack_Qty"] = np.where((convertor_main["Case_Pack_Qty"].isnull()),1,convertor_main["Case_Pack_Qty"]) 

    convertor_main["Max"] =  convertor_main["Max"].fillna(0)

    convertor_main.rename(columns= {'Case_Pack_Qty' : 'Box / Case'},inplace= True)
    convertor_main.head()

    # --- notebook cell 52 ---
    RM_Base = pd.read_excel(INV / r"dashboard_essential_files/Addon Files/RM_Convertor_Country.xlsx",sheet_name="Base_RM")

    # --- notebook cell 53 ---
    RM_Base  = RM_Base.merge(convertor_main.loc[:,["SKU","Units_Per_Set","Box / Case",'Material','Product_Category','Product_Sub_Category','Product_Type']], on = "SKU", how = "left")
    RM_Base.head()

    # --- notebook cell 54 ---
    RM_combo = pd.read_excel(INV / r"dashboard_essential_files/Addon Files/RM_Convertor_Country.xlsx",sheet_name="Combo_RM")
    RM_combo.head()

    # --- notebook cell 56 ---
    Difference_rows = convertor_main[convertor_main['Max'] != convertor_main['Box / Case']]

    convertor_main = convertor_main.drop(convertor_main[convertor_main.SKU.isnull()].index)

    # # --- notebook cell 58 ---
    # convertor_main.to_excel((DEMAND_ROOT or CENTRAL) / r"input files/helper_essential.xlsx", index = False)

    # --- notebook cell 59 ---
    with pd.ExcelWriter(INV / r"dashboard_essential_files/Country_helper.xlsx") as writer:
        convertor_main.to_excel(writer, sheet_name = "Main", index = False)
        Raw_material_convertor.to_excel(writer, sheet_name = "RMC", index = False)
        max_SKU_box_case.to_excel(writer, sheet_name = "Container_Box_case", index = False)
        RM_Base.to_excel(writer, sheet_name = "Base_RM", index = False)
        RM_combo.to_excel(writer, sheet_name = "Combo_RM", index = False)

    # --- notebook cell 62 ---
    incoming = pd.read_csv(INV / r"us/input/3G/all_orders/all_orders.csv")

    # --- notebook cell 63 ---
    # Dropping certain reference no

    incoming = incoming[~incoming.ReferenceNum.str.contains("02.2024 PHYSICAL INVENTORY")]

    # Sample orders list

    sample_values = ["02.14.24 Samples-1",  "02.14.24 Samples-2", "02.14.24 Samples-3","02.14.24 Samples-4","02.14.24 Samples-5","02.14.24 Samples Conversion","AAFE SAMPLES","jefftoddsamples",
                     "Erewhon samples","WM1gal sample","sampleall","sample","laura samples","chris samples","Giant Eagle Sample","rick samples", "pbch sample","Dosa sample", "D&D Samples 2",
                     "kehe sample","cactus samples","save mart sample","west coast samples","HEB Samples","Giant Samples","OKOPP sample","samples","photo samples","kroger sample2","DOwensSamples",
                     "walmart sample","cheryl sample 2","Giant Sample Reset","publix sample","sample kit","Joe samples","Cheryl samples","food lion sample","DG samples","Arvindbag","cdcasam",
                     "KWILSONSAMORDER","chd","Griffen Weisberg", "Mark Bruns","expowest","rangemesam","cut check","kpsam", "cdsm","ges", "mls", "wt checks","UKrework", "giantswb2","giantswb",
                     "uks2", "uks", "Olivers", "Miller","size check","cdsam6", "arvind2","arvind","AN-009",'Photo request','PA-Transfer002', 'PA-Transfer' ]

    incoming["Sample"] = np.where((incoming.ReferenceNum.isin(sample_values)),"Samples",incoming.ReferenceNum)

    incoming["PoNum"] = np.where(((incoming.PoNum.isnull()) & (incoming["Sample"] == 'Samples')), incoming['ReferenceNum'],incoming["PoNum"])

    incoming["ReferenceNum"] = np.where((incoming.Sample == 'Samples'),"Samples",incoming.ReferenceNum)

    incoming["ShipToCompany"] = np.where((incoming.ReferenceNum == 'Samples'),"Samples",incoming.ShipToCompany)
    incoming.head()

    # --- notebook cell 64 ---
    # selecting required cols
    incoming = incoming.iloc[:,[3,4,6,7,5,8,9,10,11,13]]
    # standardizing the process date
    from datetime import date
    incoming["ProcessDate"] = np.where((incoming.Status != "Closed"),incoming["ProcessDate"].fillna(date.today()),incoming["ProcessDate"])
    incoming = incoming.astype({"CreationDate" : "datetime64[ns]", "ProcessDate" : "datetime64[ns]"})

    # renaming the column
    incoming.rename(columns = {'ShipToCompany' : 'Company','SkuAndQty' : 'SKU', 'CreationDate': 'Creation_Date',
                               'ProcessDate': 'Closed_Date','ReferenceNum': 'Reference_No',"Status":"3G_Status",
                               'TrackingNumber':'Tracking No.'}, inplace = True)                
    incoming.head()

    # --- notebook cell 65 ---
    # Removing certain text from column to remove unwanted rows

    incoming['Reference_No'] = np.where(((incoming['Reference_No'] == 'phase2kitting') | (incoming['Reference_No'] == 'phase2kitting-New')), 
                               'FBA172JRLT9N', incoming['Reference_No'])

    incoming['Reference_No'] = np.where(((incoming['Reference_No'] == 'phase2kit part2') | (incoming['Reference_No'] == 'phase2kit part2-New')), 
                               'FBA172JR86H3', incoming['Reference_No'])

    incoming['Reference_No'] = np.where(((incoming.Reference_No == 'ff1') | (incoming.Reference_No == 'wmff1')),'0679568GDM', incoming.Reference_No)

    incoming['Reference_No'] = incoming['Reference_No'].apply(lambda x: list(reversed(str(x).split('AMAZON-')))[0])
    incoming['Reference_No'] = incoming['Reference_No'].apply(lambda x: list(reversed(str(x).split('Amazon ')))[0])


    incoming['Company'] = incoming['Company'].fillna("Blank_Co") 
    incoming['ShipToCountry'] = incoming['ShipToCountry'].fillna("Blank_Cont") 

    incoming = incoming[~incoming.Reference_No.str.contains("CANCELED")]
    incoming = incoming[~incoming.Company.str.contains("Blank_Co")]
    incoming = incoming[~incoming.ShipToCountry.str.contains("Blank_Cont")]

    incoming = incoming.drop(incoming[incoming.Reference_No== "FBA170RH76LG.2"].index)

    # --- notebook cell 66 ---
    incoming.head()

    # --- notebook cell 67 ---
    #Categorizing orders to each channel_________________________________________________________________________________________________________________________________
     # Initialize an empty list for Amazon
    Shipbob = []
    Amazon = []
    ThreeG = []
    Walmart = []
    Retail = []
    Tradeful=[]
    Samples=[]

    # --- notebook cell 68 ---
    tradeful_variation = ['tradefultrans', 'trdfloh2', 'trdfullaz', 'trdfulloh']
    incoming['Reference_No'] = np.where(incoming['Reference_No'].isin(tradeful_variation), 'Tradeful', incoming['Reference_No'])

    # --- notebook cell 69 ---
    # Case-insensitive search terms
    search_terms = ['amazon', 'ship', 'wal', 'ware', 'Tradeful','Samples']

    # Iterate through each search term
    for search_term in search_terms:
        # Add case-insensitive matches to the corresponding list
        for company_name in incoming['Company']:
            if search_term.lower() in company_name.lower():
                if search_term == 'amazon':
                    Amazon.append(company_name)
                elif search_term == 'ship':
                    Shipbob.append(company_name)
                elif search_term == 'wal':
                    Walmart.append(company_name)
                elif search_term == 'ware':
                    ThreeG.append(company_name)
                elif search_term == 'Samples':
                    Samples.append(company_name)
                elif search_term == ['Tradeful']:
                    Tradeful.append(company_name)

    # --- notebook cell 70 ---
    # Categorize companies not matching any search term as "Retail"
    for company_name in incoming['Company']:
        if (
            all(search_term.lower() not in company_name.lower() for search_term in search_terms) and
            company_name not in Retail
        ):
            Retail.append(company_name)

    # Apply categorization
    incoming['Company'] = np.where(incoming['Company'].isin(Shipbob), 'Shipbob', incoming['Company'])
    incoming['Company'] = np.where(incoming['Company'].isin(Amazon), 'Amazon', incoming['Company'])
    incoming['Company'] = np.where(incoming['Company'].isin(ThreeG), '3G_Internal', incoming['Company'])
    incoming['Company'] = np.where(incoming['Company'].isin(Walmart), 'Walmart', incoming['Company'])
    incoming['Company'] = np.where(incoming['Company'].isin(Tradeful), 'Tradeful', incoming['Company'])
    incoming['Company'] = np.where(incoming['Company'].isin(Tradeful), 'Samples', incoming['Company'])

    incoming['Company'] = np.where(incoming['Company'].isin(Retail), 'Retail', incoming['Company'])

    incoming.reset_index(drop=True, inplace=True)

    # --- notebook cell 71 ---
    incoming['SKU'] = incoming.SKU.fillna("Blank")
    incoming = incoming.drop(incoming[incoming.SKU == 'Blank'].index)
    incoming = incoming.reset_index(drop = True)

    # --- notebook cell 72 ---
    incoming

    # --- notebook cell 73 ---
    data = []
    for i in range(0, len(incoming)):
        x = pd.DataFrame(incoming.loc[i,["Reference_No","SKU"]].SKU.split(","), columns=["SKU"]) # type: ignore
        # x["Reference_No"] = incoming.loc[i,["Reference_No"]][0] # type: 
        x["Reference_No"] = incoming.at[i, "Reference_No"]

        data.append((x))
    data = pd.concat(data).reset_index(drop = True)

    # --- notebook cell 74 ---
    data["sku"] = data.SKU.apply(lambda x: x.split("(")[0]) # type: ignore
    data["Qty"] = data.SKU.apply(lambda x: int(x.split("(")[1].split(")")[0])) # type: ignore
    data.drop(columns = "SKU", inplace = True) # type: ignore
    data = data.loc[:, ["Reference_No", "sku", "Qty"]] # type: ignore
    data.rename(columns = {"sku": "SKU"}, inplace = True)

    # --- notebook cell 75 ---
    incom_data = data.merge(incoming.loc[:, ["OrderId","Reference_No","Company","Tracking No.","3G_Status",'PoNum', 'Creation_Date', 'Closed_Date', 'ShipToCountry']], 
                               left_on = "Reference_No", right_on = "Reference_No", how = "outer")
    incom_data.head()

    # --- notebook cell 76 ---
    # Changing SKU Names 
    incom_data.SKU = incom_data.SKU.apply(lambda x: str(x).split('KIT')[0])
    incom_data['SKU'] = incom_data['SKU'].apply(lambda x: list(reversed(str(x).split('amzn.gr.')))[0])

    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    incom_data = clean_warehouse_sku_column(
        incom_data, sku_column="SKU", sku_mapping=sku_mapping
    )

    incom_data["3G_Status"] = np.where((incom_data["3G_Status"]!="Closed"),"Open", incom_data["3G_Status"])

    incom_data.head()

    # --- notebook cell 77 ---
    incom_data["Tracking No."] = np.where((incom_data["Tracking No."].isnull()) & (incom_data.Company =="Amazon"), incom_data["Reference_No"], incom_data["Tracking No."])
    incom_data["Tracking No."] = np.where(((incom_data["Tracking No."].isnull()) & (incom_data['3G_Status']!="Closed")),"Order In-Transit from 3G",incom_data["Reference_No"])
    incom_data["PoNum"] = np.where((incom_data["PoNum"].isnull()) & (incom_data.Company =="Retail"), incom_data["Reference_No"], incom_data["PoNum"])

    incom_data.reset_index(drop=True)
    incom_data.head()

    # --- notebook cell 78 ---
    # Fromatting PONum to align it with retail orders
    incom_data.PoNum = incom_data.PoNum.apply(lambda x: list(reversed(str(x).split('unfi')))[0])
    incom_data.PoNum = incom_data.PoNum.apply(lambda x: list(reversed(str(x).split('-')))[0])
    incom_data.PoNum = incom_data.PoNum.apply(lambda x: list(reversed(str(x).split('PO')))[0])
    incom_data.PoNum = incom_data.PoNum.apply(lambda x: list(reversed(str(x).split('po')))[0])
    incom_data.PoNum = incom_data.PoNum.apply(lambda x: list(reversed(str(x).split(' ')))[0])
    incom_data.PONum = incom_data.PoNum.apply(lambda x: list(reversed(str(x).split('SP-PO')))[0])
    incom_data.PoNum = incom_data.PoNum.apply(lambda x: list(reversed(str(x).split('SP-PO ')))[0])


    incom_data.PoNum= np.where(((incom_data.Reference_No =="C&S PO291963") | (incom_data.Reference_No =="C&SPO291963")), '291963', incom_data.PoNum)
    incom_data.PoNum= np.where(((incom_data.Reference_No =="kehe PO5643207") | (incom_data.Reference_No =="kehePO5643207")), '5643207', incom_data.PoNum)
    incom_data.PoNum= np.where(((incom_data.Reference_No =="kehe PO5645661") | (incom_data.Reference_No =="kehePO5645661")), '5645661', incom_data.PoNum)
    incom_data.PoNum= np.where(((incom_data.Reference_No =="kehe PO5649847") | (incom_data.Reference_No =="kehePO5649847")), '5649847', incom_data.PoNum)
    incom_data.PoNum= np.where(((incom_data.Reference_No =="C&S PO831962") | (incom_data.Reference_No =="C&SPO831962")), '831962', incom_data.PoNum)
    incom_data.PoNum= np.where(((incom_data.Reference_No =="C&S PO815799") | (incom_data.Reference_No =="C&SPO815799")), '815799', incom_data.PoNum)
    incom_data.PoNum= np.where(((incom_data.Reference_No =="kehePO5598908") | (incom_data.Reference_No =="kehe PO5598908")), '5598908', incom_data.PoNum)

    incom_data.SKU = incom_data.SKU.apply(lambda x: list(reversed(str(x).split('CASE')))[0])
    incom_data.SKU= np.where(((incom_data.SKU =="BST16")), 'BSTL16', incom_data.SKU)
    incom_data.SKU= np.where(((incom_data.SKU =="PLPB8+10SQ50")), 'PLPB7&10SQ50', incom_data.SKU)
    incom_data.SKU= np.where(((incom_data.SKU =="PLPB8+10SQ100")), 'PLPB7&10SQ100', incom_data.SKU)
    incom_data.SKU= np.where(((incom_data.SKU =="PLPB8+10SQ200")), 'PLPB7&10SQ200', incom_data.SKU)
    incom_data.SKU= np.where(((incom_data.SKU =="CBP6RO100c12")), 'CBP6RO100', incom_data.SKU)
    incom_data.SKU= np.where(((incom_data.SKU =="CTB4G100")), 'CTBN4G100', incom_data.SKU)


    incom_data.head()

    # --- notebook cell 79 ---
    incom_data['OrderId'] = incom_data['OrderId'].astype('string')

    # --- notebook cell 80 ---
    # Add a prefix to 'PoNum' based on the condition
    prefix = 'PO'
    incom_data['PoNum'] = np.where(incom_data['Company'] == 'Retail', prefix + incom_data['PoNum'].astype(str), incom_data['PoNum'])


    # Update 'PoNum' and 'Company' based on the 1 condition
    condition_1 = incom_data['Reference_No'] == 'kehe5861741'
    incom_data.loc[condition_1, 'PoNum'] = 'PO5861741'
    incom_data.loc[condition_1, 'Company'] = 'Retail'


    # Update 'CA Reference No' and 'Company' based on the 2 condition
    condition_1 = incom_data['Reference_No'] == 'FBA17CMB361R'
    incom_data.loc[condition_1, 'OrderId'] = 'FBA17CZ7170K'
    incom_data.loc[condition_1, 'Reference_No'] = 'FBA17CZ7170K'
    incom_data.loc[condition_1, 'PoNum'] = 'FBA17CZ7170KU'

    # Update 'CA Reference No'' and 'Company' based on the 3 condition
    condition_1 = incom_data['Reference_No'] == 'FBA17CMB362D'
    incom_data.loc[condition_1, 'OrderId'] = 'FBA17CZ7170K'
    incom_data.loc[condition_1, 'Reference_No'] = 'FBA17CZ7170K'
    incom_data.loc[condition_1, 'PoNum'] = 'FBA17CZ7170KU'

    # Update 'PoNum' and 'Company' based on the second condition
    condition_2 = incom_data['PoNum'].isin(['POnan',"POwave","POtrdfloh2","POcalitb","PO calitrans830","POtradefullaz1","POtradefulloh1","POES23","POcrowe","POmitch1","POcjones","POSAL","POSalas Foods1",
                                          "POsample","POalliance rick","PO 10798547 truck2","PO10780500 t1","POCBP6RO100KIT","POCBB12RO100KIT","POCBB12RO500KIT","POCBB12RO200KIT","POCBP10RO200KIT",
                                          "POcbp6ro500kit","POcbp6ro200 kit","POhyvee samp","POGreen Pond CPU","POsample","POpeggy","POGerardo","POD&D Samples","POWakefern","POErewhon sample",
                                          "POFT Sample","POHOT","POcactus sample","POAlliance Road Show","POAlliance sample","POsavemart sample","POwc samples","POokoppsample","POsamples",
                                          "POphoto samples","PO east"])
    incom_data.loc[condition_2, 'PoNum'] = 'Samples'
    incom_data.loc[condition_2, 'Company'] = 'Samples'

    incom_data['Reference_No'] = np.where((incom_data['Reference_No'] == 'wm2941559GDM'), '2941559GDM',incom_data['Reference_No'] )

    #Applying pivot
    incom_data = pd.pivot_table( incom_data,index = ['Reference_No','OrderId', 'Company', 'Tracking No.','3G_Status', 'PoNum', 'Creation_Date', 'Closed_Date', 'ShipToCountry','SKU'],
                                 values = ['Qty'], aggfunc = 'sum').reset_index()

    incom_data['Creation_Date'] = np.where(incom_data['Creation_Date'].astype(str).str.contains('-'),
             pd.to_datetime(incom_data['Creation_Date']).dt.strftime('%d-%b-%Y'),
             pd.to_datetime(incom_data['Creation_Date'], dayfirst=False).dt.strftime('%d-%b-%Y'))

    incom_data['Closed_Date'] = np.where(incom_data['Closed_Date'].astype(str).str.contains('-'),
             pd.to_datetime(incom_data['Closed_Date']).dt.strftime('%d-%b-%Y'),
             pd.to_datetime(incom_data['Closed_Date'], dayfirst=False).dt.strftime('%d-%b-%Y'))

    # --- notebook cell 83 ---
    ### Old Format (Open & Closed) 
    col_list = ["CUSTOMERORDERNUMBER", "ORDERNUMBER","CARRIERNAME","CUSTOMERLOTREFERENCE", "STATUS", "WAREHOUSESKU", "QTY","Unnamed: 17"]
    Updk_O1= pd.read_excel(INV / r"us/input/updike/shipment_orders/shipmentorders.xlsx", usecols= col_list)

    # --- notebook cell 84 ---
    Updk_O1.rename(columns = {'CUSTOMERORDERNUMBER' : 'Reference_No',"Unnamed: 17" :"Order_Closed_Date",
                                    'CARRIERNAME' : 'Company', 'STATUS': 'Updike_Status',
                               'WAREHOUSESKU': 'SKU','CUSTOMERLOTREFERENCE': 'Traking_no',
                               'QTY':'Ship_Qty_Updike'}, inplace = True)             

    #Applying Pivot 
    Updk_O1 = pd.pivot_table(Updk_O1, index=["ORDERNUMBER","Reference_No","Company","Updike_Status","Order_Closed_Date","SKU",],values="Ship_Qty_Updike", aggfunc="sum").reset_index()
    Updk_O1.head()

    # --- notebook cell 86 ---
    Updk_New_Open = pd.read_excel(
        INV / r"us\input\updike\Activity Lines\WebLink - Pending Transaction Lines.xlsx",
        skipfooter=1
    )

    Updk_New_Open = Updk_New_Open.drop(Updk_New_Open[Updk_New_Open['Document Type']!= "Shipment"].index) 

    unstructure = ['3419570834','7472189918']

    Updk_New_Open['Customer Order#'] =np.where((Updk_New_Open['Customer Order#'].isin(unstructure)),'FBA' + Updk_New_Open['Customer Order#'], Updk_New_Open['Customer Order#'])
    Updk_New_Open.head()

    # --- notebook cell 87 ---
    ### New Format (Open & Closed) 
    Updk_New_Open = Updk_New_Open.loc[:,["Document","Customer Order#","Doc Date", "Item", "Count Qty" ]]
    Updk_New_Open.rename(columns={"Document" : "ORDERNUMBER","Customer Order#" : "Reference_No","Doc Date": "Order_Closed_Date","Item" : "SKU","Count Qty" : "Ship_Qty_Updike"},inplace = True)
    Updk_New_Open.head()

    # --- notebook cell 88 ---
    # Define a function to add prefix "PO" if the value is numeric
    def add_prefix(value):
        if isinstance(value, (int, float)) and not pd.isnull(value):
            return "PO" + str(int(value))
        else:
            return value

    # Apply the function to the Reference_No column
    Updk_New_Open['Reference_No'] = Updk_New_Open['Reference_No'].apply(add_prefix) # type: ignore

    # --- notebook cell 89 ---
    # Step-by-step cleanup and conversion
    Updk_New_Open["Ship_Qty_Updike"] = (
        Updk_New_Open["Ship_Qty_Updike"]
        .astype(str)                               # Convert everything to string
        .str.replace(',', '', regex=False)         # Remove thousand separators
        .str.extract(r'(-?/d+/.?/d*)')[0]           # Extract numeric part safely (optional but safe)
        .astype(float)                             
        .abs()                                      # Take absolute value
    )


    Updk_New_Open

    # --- notebook cell 90 ---
    Updk_New_Open['Ship_Qty_Updike'].sum()

    # --- notebook cell 92 ---
    Updk_New_Closed = pd.read_excel(INV / r"us/input/updike/Activity Lines/WebLink - Detail History.xlsx")

    unstructure2 = ['3419570834','7472189918']

    Updk_New_Closed['Customer Order#'] =np.where((Updk_New_Closed['Customer Order#'].isin(unstructure2)),'FBA' + Updk_New_Closed['Customer Order#'], Updk_New_Closed['Customer Order#'])

    Updk_New_Closed.head()

    # --- notebook cell 93 ---
    Updk_New_Closed = Updk_New_Closed.drop(Updk_New_Closed[Updk_New_Closed["Document Type"] != "Shipment"].index).reset_index(drop=True)

    Updk_New_Closed = Updk_New_Closed.loc[:,["Document","Customer Order#","Doc Date", "Item", "Count Qty" ]]

    Updk_New_Closed.rename(columns={"Document" : "ORDERNUMBER","Customer Order#" : "Reference_No","Doc Date": "Order_Closed_Date","Item" : "SKU","Count Qty" : "Ship_Qty_Updike"},inplace = True)

    # Use the apply method with abs() for selected columns
    Updk_New_Closed.Ship_Qty_Updike = Updk_New_Closed.Ship_Qty_Updike.apply(lambda x: list(reversed(x.split('-')))[0])

    Updk_New_Closed["Ship_Qty_Updike"] = Updk_New_Closed["Ship_Qty_Updike"].apply(lambda x: int(str(x).replace(",","")))
    Updk_New_Closed = Updk_New_Closed.astype({'Ship_Qty_Updike' : 'float'})

    #Updk_New_Closed["Ship_Qty"] = Updk_New_Closed["Ship_Qty"].apply(abs)

    Updk_New_Closed.head(2)

    # --- notebook cell 94 ---
    # Merging New orders Dataframe
    Updk_New_order = pd.concat([Updk_New_Closed, Updk_New_Open]).reset_index(drop = True)

    # BST16/BKDO normalization via esh_sku_cleaning.DEFAULT_SKU_NORMALIZATION
    # Merging Old & New Orders Reports
    Updk_New_order = pd.concat([Updk_New_order, Updk_O1]).reset_index(drop = True)

    # Creating Col Updike Status
    Updk_New_order["Updike_Status"] = np.where((Updk_New_order.Order_Closed_Date.isnull()), "Receiving", "Closed")

    Updk_New_order.head(2)

    # --- notebook cell 95 ---
    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    Updk_New_order = clean_warehouse_sku_column(
        Updk_New_order, sku_column="SKU", sku_mapping=sku_mapping
    )
    Updk_New_order.head()

    # --- notebook cell 96 ---
    Updk_New_order["Reference_No"] = np.where((Updk_New_order.Reference_No == "FBA172JLY7G7"),"FBA172JN8S2C",
                            np.where((Updk_New_order.Reference_No == "FBA172JN8S2C"),"FBA172JLY7G7",Updk_New_order["Reference_No"]))

    Updk_New_order["Reference_No"] = np.where((Updk_New_order.Reference_No == "TransferEdison"),"Edison",Updk_New_order["Reference_No"])

    Updk_New_order['SKU'] =np.where((Updk_New_order.Reference_No==872076) & (Updk_New_order.SKU=="CBP9RO100"), "CBP9RO20",Updk_New_order['SKU'])
    Updk_New_order['SKU'] =np.where((Updk_New_order.Reference_No==872077) & (Updk_New_order.SKU=="CBP9RO100"), "CBP9RO20",Updk_New_order['SKU'])
    Updk_New_order['SKU'] =np.where((Updk_New_order.Reference_No==5980849) & (Updk_New_order.SKU=="CBP9RO100"), "CBP9RO20",Updk_New_order['SKU'])


    Updk_New_order = Updk_New_order.drop(Updk_New_order[Updk_New_order.Reference_No.isnull()].index) 


    Updk_New_order["Carrier"] = Updk_New_order["Reference_No"]
    Updk_New_order.head()

    # --- notebook cell 97 ---
    #Categorizing orders to each channel_________________________________________________________________________________________________________________________________
     # Initialize an empty list for Amazon
    Tradeful = []
    Amazon = []
    Sample = []
    Walmart = []
    Retail = []
    ThreeG = []

    # --- notebook cell 98 ---
    # Case-insensitive search terms
    search_terms = ['FBA', 'AMAZON', 'UK SAMPLES', 'Transfer', 'TRADEFULL TRANSFER', 'wal', 'SAMPLE', 'TP TO 3G', 'Edison', 'GDM','RUSHEDORDER','CHRIS DICKMAN']

    # Iterate through each search term
    for search_term in search_terms:
        # Add case-insensitive matches to the corresponding list
        for company_name in Updk_New_order['Carrier']:
            if search_term.lower() in company_name.lower():
                if search_term in ['FBA', 'Amazon', 'UK SAMPLES']: 
                    Amazon.append(company_name)
                elif search_term == 'TRADEFULL TRANSFER':
                    Tradeful.append(company_name)
                elif search_term in ['TRADEFULL']:
                    Tradeful.append(company_name)
                elif search_term in ['wal', 'GDM']:
                    Walmart.append(company_name)
                elif search_term == 'Edison':
                    ThreeG.append(company_name)  # Append 'Edison' to the ThreeG list
                elif search_term == 'TP TO 3G':
                    ThreeG.append(company_name)  # Append 'TP TO 3G' to the ThreeG list
                elif search_term in ['RUSHEDORDER','CHRIS DICKMAN']:
                    Sample.append(company_name)
                elif search_term in ['SAMPLE', 'Transfer']:
                    Sample.append(company_name)

    # --- notebook cell 99 ---
    # Categorize companies not matching any search term as "Retail"
    for company_name in Updk_New_order['Carrier']:
        if (
            all(search_term.lower() not in company_name.lower() for search_term in search_terms) and
            company_name not in Retail
        ):
            Retail.append(company_name)

    # Apply categorization
    Updk_New_order['Carrier'] = np.where(Updk_New_order['Carrier'].isin(Tradeful), 'Tradeful', Updk_New_order['Carrier'])
    Updk_New_order['Carrier'] = np.where(Updk_New_order['Carrier'].isin(Amazon), 'Amazon', Updk_New_order['Carrier'])
    Updk_New_order['Carrier'] = np.where(Updk_New_order['Carrier'].isin(Sample), 'Sample', Updk_New_order['Carrier'])
    Updk_New_order['Carrier'] = np.where(Updk_New_order['Carrier'].isin(Walmart), 'Walmart', Updk_New_order['Carrier'])
    Updk_New_order['Carrier'] = np.where(Updk_New_order['Carrier'].isin(ThreeG), 'ThreeG', Updk_New_order['Carrier'])
    Updk_New_order['Carrier'] = np.where(Updk_New_order['Carrier'].isin(Retail), 'Retail', Updk_New_order['Carrier'])

    Updk_New_order.reset_index(drop=True, inplace=True)

    Updk_New_order.drop(columns = ["Company"], inplace = True)

    Updk_New_order["Updike_Status"] = np.where((Updk_New_order["Updike_Status"] == "Closed"), "Shipped", Updk_New_order["Updike_Status"])
    Updk_New_order["Reference_No"] = np.where((Updk_New_order["Reference_No"] == "FBA178PYVBR6" ),"FBA178PWHN9F", Updk_New_order["Reference_No"] )
    Updk_New_order["Reference_No"] = np.where((Updk_New_order["Reference_No"] == "FBA17HNC9LRW-2" ),"FBA17HNC9LRW", Updk_New_order["Reference_No"] )

    # Define the condition
    condition = Updk_New_order['Carrier'].str.contains('GDM')

    Updk_New_order["Carrier"] = np.where(condition, 'Walmart', Updk_New_order['Carrier'])

    Updk_New_order.head()

    # --- notebook cell 100 ---
    # Special Conditions
    Updk_New_order["Carrier"] = np.where(((Updk_New_order["Reference_No"] =="UK SAMPLES" )), "Sample", Updk_New_order["Carrier"]) 

    adding_PO = ['493589','738266']
    Updk_New_order["Reference_No"] = np.where(((Updk_New_order["Reference_No"].isin(adding_PO))),'PO'+ Updk_New_order["Reference_No"], Updk_New_order["Reference_No"]) 

    Updk_New_order["SKU"] = np.where(((Updk_New_order["Reference_No"] =="PO5980849" ) & (Updk_New_order["SKU"] == "CBP9RO100")), "CBP9RO20", Updk_New_order["SKU"]) 
    Updk_New_order["SKU"] = np.where(((Updk_New_order["Reference_No"] =="PO872076" ) & (Updk_New_order["SKU"] == "CBP9RO100")), "CBP9RO20", Updk_New_order["SKU"]) 
    Updk_New_order["SKU"] = np.where(((Updk_New_order["Reference_No"] =="PO872077" ) & (Updk_New_order["SKU"] == "CBP9RO100")), "CBP9RO20", Updk_New_order["SKU"])

    # --- notebook cell 101 ---
    Updk_New_order['Order_Closed_Date'] = np.where(Updk_New_order['Order_Closed_Date'].astype(str).str.contains('-'),
             pd.to_datetime(Updk_New_order['Order_Closed_Date']).dt.strftime('%d-%b-%Y'),
             pd.to_datetime(Updk_New_order['Order_Closed_Date'], dayfirst=False).dt.strftime('%d-%b-%Y'))

    # --- notebook cell 102 ---
    with pd.ExcelWriter(
        INV / r"dashboard_essential_files\WH_Orders_Standard_File.xlsx"
    ) as writer:
        incom_data.to_excel(writer, sheet_name = "3G-Orders", index = False)
        Updk_New_order.to_excel(writer, sheet_name = "Updike-Orders", index = False)

    # --- notebook cell 106 ---
    UDreceipts_old = pd.read_excel(INV / r"us/input/updike/warehouse_receipts/warehousereceipts.xls")

    # --- notebook cell 107 ---
    UDreceipts_old = UDreceipts_old.loc[:,['CUSTOMERORDERNUMBER','DELIVERYDATE','WAREHOUSESKU','QTYRECEIVED']]
    UDreceipts_old.info()

    # --- notebook cell 108 ---
    UDreceipts_old= UDreceipts_old.rename (columns = {'CUSTOMERORDERNUMBER':'Reference_No', 'DELIVERYDATE': 'Delivery_Date','WAREHOUSESKU':'SKU','QTYRECEIVED':'Received Qty'})

    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    UDreceipts_old = clean_warehouse_sku_column(
        UDreceipts_old, sku_column="SKU", sku_mapping=sku_mapping
    )
    UDreceipts_old.head()

    # --- notebook cell 109 ---
    UDreceipts_old['SKU'] =np.where((UDreceipts_old['Reference_No']=='MSDU8619310') & (UDreceipts_old['SKU']=="CBP9RO100"), "CBP9RO20",UDreceipts_old['SKU'])
    UDreceipts_old['SKU'] =np.where((UDreceipts_old['Reference_No']=='MSDU7178463') & (UDreceipts_old['SKU']=="CBP9RO100"), "CBP9RO20",UDreceipts_old['SKU'])

    UDreceipts_old['Reference_No'] =np.where((UDreceipts_old['Reference_No'] =='TBBU6528916'), "TGBU6528916",UDreceipts_old['Reference_No'])
    UDreceipts_old['Reference_No'] =np.where((UDreceipts_old['Reference_No'] =='670-888349894'), "Cont-#143-20520750612",UDreceipts_old['Reference_No'])
    UDreceipts_old.head()

    # --- notebook cell 111 ---
    UDreceipts_new = pd.read_excel(INV / r"us/input/updike/Activity Lines/WebLink - Detail History.xlsx")

    # --- notebook cell 112 ---
    ## Updike New Format

    UDreceipts_new =UDreceipts_new.drop(UDreceipts_new[UDreceipts_new["Document Type"]!= 'Receipt'].index)
    UDreceipts_new = UDreceipts_new.loc[:,["Customer Order#","Doc Date",'Item',"Count Qty","Count Unit"]]
    UDreceipts_new.rename(columns={"Customer Order#" : "Reference_No","Doc Date": "Delivery_Date", "Item" : "SKU", "Count Qty" : "Received Qty","Count Unit" : "UOM"},inplace = True)
    UDreceipts_new.head()

    # --- notebook cell 113 ---
    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    UDreceipts_new = clean_warehouse_sku_column(
        UDreceipts_new, sku_column="SKU", sku_mapping=sku_mapping
    )
    UDreceipts_new["Received Qty"] = pd.to_numeric(UDreceipts_new["Received Qty"].str.replace(',', '', regex=True), errors='coerce')
    UDreceipts_new.head()

    # --- notebook cell 114 ---
    # Merging Old & New Receipts Dataframe
    UDreceipts = pd.concat([UDreceipts_new, UDreceipts_old]).reset_index(drop = True)

    # BST16/BKDO normalization via esh_sku_cleaning.DEFAULT_SKU_NORMALIZATION
    UDreceipts['Delivery_Date'] = UDreceipts['Delivery_Date'].apply(
        lambda x: pd.to_datetime(x).strftime("%d-%b-%Y") if pd.to_datetime(x, errors='coerce') is not pd.NaT else None)
    UDreceipts.head()

    # --- notebook cell 116 ---
    path =INV / r"us/input/3G/receipts"

    # --- notebook cell 117 ---

    filelist1 = []

    for root, dirs, files in os.walk(path):
        for file in files:
            filelist1.append(os.path.join(root,file)) #append the file name to the list"""

    len(filelist1)

    # --- notebook cell 118 ---
    data1 = []
    for i in filelist1:
        data1.append(pd.read_excel(i))
    rect = pd.concat(data1).reset_index(drop=True)
    rect.info()

    # --- notebook cell 119 ---
    rect.rename(columns = {"Reference Number": "Reference_No","Transaction ID": "TID"}, inplace = True)

    #Drop Rows with blank Status
    rect = rect.drop(rect[rect.SKU.isnull()].index) 


    rect["Reference_No"] = rect.Reference_No.apply(lambda x: x.split("-LCL")[0])
    rect["Reference_No"] = rect.Reference_No.apply(lambda x: x.split(" -")[0])
    rect["Reference_No"] = rect.Reference_No.apply(lambda x: x.split("-")[0])

    rect["Creation Date"] = rect["Creation Date"].apply(lambda x: x.split(" ")[0])
    rect["Arrival Date"] = rect["Arrival Date"].apply(lambda x: x.split(" ")[0])

    rect["Reference_No"] = np.where((rect.Reference_No == "#97"),"CON36984052975",rect["Reference_No"])
    rect["Reference_No"] = np.where((rect.Reference_No == "5.30 Inbound-ziplocks") | (rect.Reference_No == "5.30 Inbound"),"TRHU8691720",rect["Reference_No"])
    rect["SKU"] = np.where(((rect.Reference_No == "TRHU8691720") &(rect.SKU == "5.30 Inbound-ziplocks(6)")),"CZLS25(600),CZLSW25(350)",rect["SKU"])

    rect.rename(columns = {"Arrival Date": "Creation_3G","Creation Date": "Arrival_3G","Transaction ID": 'TID'}, inplace = True)
    rect = rect.loc[:,["TID","Reference_No","Creation_3G","Arrival_3G","SKU","Notes"]]

    # Drop Rows with specific 'Reference_No'
    a = ["WO# 920", "West Coast Transfer 06.28.23", "nin a1 T6 & T7", "nin a1 t1", "Amazonkit 3&4","nin a1 t2", "nin a1 t3", "nin a1 t4", "nin a1 t5", "Cali6", "Eco Soul Conversion ", "Eco Soul Conversion",
         "Eco Soul Sample Conversion", "S11926 Transfer", "Samples", "Samples Inv 2207233","Shipbob Cups", "Shipbob Cups 2", "TB Trans Cali", "West Coast Transfer 06.30.23", "Samples", "CS490147","EASTER SEALS" ]
    for i in a:
        rect = rect.drop(rect[rect.Reference_No== i].index)


    from datetime import datetime
    rect['Arrival_3G']= pd.to_datetime(rect.Arrival_3G)
    rect['Creation_3G']= pd.to_datetime(rect.Creation_3G)

    rect.head()

    # --- notebook cell 120 ---
    rect_qty = rect.loc[:, ["Reference_No", "SKU"]]

    rect.drop(columns = [ "SKU"], inplace = True)
    # Reset the index
    rect_qty = rect_qty.reset_index(drop=True)

    # Display the head of the DataFrame
    rect_qty.head()

    # --- notebook cell 121 ---
    data = []

    for i in range(0, len(rect_qty)):
        # Split the "SKU" column by comma
        sku_value = rect_qty.loc[i, "SKU"].split(",") # type: ignore

        # Create a DataFrame with "SKU," "Company," and "Country" columns
        x = pd.DataFrame(sku_value, columns=["SKU"])
        x["Reference_No"] = rect_qty.loc[i, "Reference_No"]

        data.append(x)

    # Concatenate the DataFrames in the "data" list
    data = pd.concat(data).reset_index(drop=True)

    # Reorder the columns as needed
    data = data[["Reference_No", "SKU"]]

    # Display the resulting DataFrame
    data.info()
    data.head()

    # --- notebook cell 122 ---
    # Split 'SKU' column into 'sku' and 'Qty'
    data['sku'] = data['SKU'].apply(lambda x: x.split("(")[0] if "(" in x else None) # type: ignore
    data['Qty'] = data['SKU'].apply(lambda x: int(x.split("(")[1].split(")")[0]) if "(" in x and ")" in x else None) # type: ignore

    # Drop the original 'SKU' column
    data.drop(columns='SKU', inplace=True) # type: ignore

    # Drop rows where 'sku' or 'Qty' is None
    data.dropna(subset=['sku', 'Qty'], inplace=True) # type: ignore

    # Reorder columns and rename 'sku' to 'SKU'
    data = data.loc[:, ['Reference_No', 'sku', 'Qty']] # type: ignore
    data.rename(columns={'sku': 'SKU'}, inplace=True)

    # Create a pivot table to aggregate quantities
    rect_qty = data.pivot_table(index=['Reference_No', 'SKU'], values='Qty', aggfunc='sum').reset_index()

    rect_qty["SKU"] = np.where(((rect_qty.SKU =="PLPB8&10SQ200") | (rect_qty.SKU =="PLPB8+10SQ200")),"PLPB7&10SQ200",rect_qty["SKU"])   
    rect_qty["SKU"] = np.where(((rect_qty.SKU =="PLPB8&10SQ50") | (rect_qty.SKU =="PLPB8+10SQ50")),"PLPB7&10SQ50",rect_qty["SKU"])
    rect_qty["SKU"] = np.where(((rect_qty.SKU =="PLPB8&10SQ100") | (rect_qty.SKU =="PLPB8+10SQ100")),"PLPB7&10SQ100",rect_qty["SKU"])

    # Define the substrings to remove
    case_patterns = ["CASE12", "CASE8", "CASE24", "CASE2", "CASE6"]

    # Replace each pattern in the SKU column with an empty string
    rect_qty["SKU"] = rect_qty["SKU"].replace(case_patterns, "", regex=True)

    # Display information about the DataFrame
    rect_qty.head()

    # --- notebook cell 123 ---
    rect_qty['SKU'] = rect_qty['SKU'].apply(lambda x: list(reversed(str(x).split('amzn.gr.')))[0])
    rect_qty.SKU = rect_qty.SKU.apply(lambda x: str(x).split('CZLG20CASE12')[0])

    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    rect_qty = clean_warehouse_sku_column(
        rect_qty, sku_column="SKU", sku_mapping=sku_mapping
    )

    rect_qty["SKU"] = np.where(((rect_qty.SKU =="PLPB8&10SQ200") | (rect_qty.SKU =="PLPB8+10SQ200")),"PLPB7&10SQ200",rect_qty["SKU"])   
    rect_qty["SKU"] = np.where(((rect_qty.SKU =="PLPB8&10SQ50") | (rect_qty.SKU =="PLPB8+10SQ50")),"PLPB7&10SQ50",rect_qty["SKU"])
    rect_qty["SKU"] = np.where(((rect_qty.SKU =="PLPB8&10SQ100") | (rect_qty.SKU =="PLPB8+10SQ100")),"PLPB7&10SQ100",rect_qty["SKU"])
    rect_qty["SKU"] = np.where((rect_qty.SKU =="CBP6RO100c12"),"CBP6RO100",rect_qty["SKU"])
    rect_qty["SKU"] = np.where(((rect_qty.SKU =="PLP6SQ50")& (rect_qty.Reference_No =="HLBU2782670")),"PLP6RO50",rect_qty["SKU"])

    # Correcting Discrepancy in Reference no BEAU4167210

    rect_qty["Qty"] = np.where(((rect_qty.SKU =="PLP10RO50") & (rect_qty.Reference_No =="BEAU4167210")),100,rect_qty["Qty"])  
    rect_qty["Qty"] = np.where(((rect_qty.SKU =="PLP10SQ50") & (rect_qty.Reference_No =="BEAU4167210")),250,rect_qty["Qty"])  
    rect_qty["Qty"] = np.where(((rect_qty.SKU =="PLP8SQ50") & (rect_qty.Reference_No =="BEAU4167210")),150,rect_qty["Qty"])  


    # Create a pivot table to aggregate quantities
    rect_qty = rect_qty.pivot_table(index=['Reference_No', 'SKU'], values='Qty', aggfunc='sum').reset_index()

    # Merging rect qty with main dataframe
    rect = pd.merge(rect, rect_qty, on = "Reference_No", how = "left")

    rect['Creation_3G'] = np.where(rect['Creation_3G'].astype(str).str.contains('-'),
             pd.to_datetime(rect['Creation_3G']).dt.strftime('%d-%b-%Y'),
             pd.to_datetime(rect['Creation_3G'], dayfirst=False).dt.strftime('%d-%b-%Y'))

    rect['Arrival_3G'] = np.where(rect['Arrival_3G'].astype(str).str.contains('-'),
             pd.to_datetime(rect['Arrival_3G']).dt.strftime('%d-%b-%Y'),
             pd.to_datetime(rect['Arrival_3G'], dayfirst=False).dt.strftime('%d-%b-%Y'))

    rect.head()

    # --- notebook cell 124 ---
    with pd.ExcelWriter(INV / r"dashboard_essential_files/WH_Receipts_Standard_File.xlsx") as writer:
        rect.to_excel(writer, sheet_name = "3G-Receipts", index = False)
        UDreceipts.to_excel(writer, sheet_name = "Updike-Receipts", index = False)

    # --- notebook cell 126 ---
    path =INV / r"us/input/walmart/inbound_receipts"

    filelisted = []

    for root, dirs, files in os.walk(path):
        for file in files:
            filelisted.append(os.path.join(root,file)) #append the file name to the list"""
    len(filelisted)

    # --- notebook cell 127 ---
    df6 = []
    for i in filelisted:
        df6.append(pd.read_csv(i))
    walrecep = pd.concat(df6).reset_index(drop=True)
    # Deleting cancelled shipments
    dropping_Status = ["Cancelled", "SUSPENDED"]
    walrecep = walrecep.drop(walrecep[walrecep["PO Status"].isin(dropping_Status)].index) 
    walrecep.to_excel(INV / r"dashboard_essential_files/Walmart_all_shipment.xlsx", index = False)
    walrecep.head(2)

    # --- notebook cell 129 ---
    def to_snake(name: str) -> str:
        """Convert column name to snake_case format."""
        name = name.strip()
        name = name.lower()
        name = re.sub(r'[^a-z0-9]+', '_', name)
        name = re.sub(r'_+', '_', name)
        name = name.strip('_')
        return name

    # --- notebook cell 130 ---
    container_sku.columns = [to_snake(col) for col in container_sku.columns]

    convertor_main.columns = [to_snake(col) for col in convertor_main.columns]

    container.columns = [to_snake(col) for col in container.columns]
    container_sku

    # --- notebook cell 131 ---
    import time
    import pandas as pd
    from io import BytesIO
    from azure.storage.blob import BlobServiceClient
    from azure.core.exceptions import ServiceResponseError

    # ====================================================================
    # AZURE CONFIG
    # ====================================================================
    AZURE_CONNECTION_STRING = (
        "DefaultEndpointsProtocol=https;AccountName=thriveclientdatabase;AccountKey=t3YQjkSXWXafdSIzp48QxNgmuW8BSh+6FzHaEy6VhGbgINYgo7Sica0BZw9sAKEPbwBcjqqhK5p6+AStuxDzSA==;EndpointSuffix=core.windows.net"
    )

    AZURE_CONTAINER = "thrive-client-ecosoulhome"   # must be lowercase, valid format

    # ====================================================================
    # UPLOAD WITH RETRY
    # ====================================================================
    def upload_blob_with_retry(blob_client, data, blob_path, max_retries=3, max_concurrency=4, timeout=600):
        """Upload blob with retry + exponential backoff."""
        for attempt in range(max_retries):
            try:
                data.seek(0)

                blob_client.upload_blob(
                    data,
                    overwrite=True,
                    max_concurrency=max_concurrency,
                    timeout=timeout
                )

                print(f"✅ Uploaded: {blob_path}")
                return

            except ServiceResponseError as e:
                wait = (2 ** attempt) * 5
                print(f"⚠️ Azure upload failed (Attempt {attempt+1}/{max_retries}) for {blob_path}")
                print(f"   Error: {str(e)}")
                print(f"   Retrying in {wait} sec...\n")
                time.sleep(wait)

            except Exception as e:
                print(f"❌ Unexpected error for {blob_path}: {str(e)}")
                raise

        print(f"❌ Final Failure: Could NOT upload {blob_path} after {max_retries} attempts.")
        raise RuntimeError("Upload Failed")


    def upload_to_azure_csv(df, blob_path, connection_string, container_name):
        df = df.copy()

        # Fix all object columns
        object_cols = df.select_dtypes(include='object').columns
        df[object_cols] = df[object_cols].astype(str)

        # Replace NaN with None
        df = df.where(pd.notnull(df), None)

        df.columns = [to_snake(col) for col in df.columns]


        buffer = BytesIO()
        df.to_csv(buffer, index=False)
        buffer.seek(0)


        blob_service_client = BlobServiceClient.from_connection_string(
            connection_string,
            connection_timeout=600,
            read_timeout=600
        )

        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)
        upload_blob_with_retry(blob_client, buffer, blob_path)

    upload_to_azure_csv(convertor_main, "sanity_data/datahive/inventory/item_master.csv",AZURE_CONNECTION_STRING, AZURE_CONTAINER)
    upload_to_azure_csv(container_sku, "sanity_data/datahive/inventory/container_tracker.csv",AZURE_CONNECTION_STRING, AZURE_CONTAINER)
    upload_to_azure_csv(container, "sanity_data/datahive/inventory/container_details.csv",AZURE_CONNECTION_STRING, AZURE_CONTAINER)


    return None


def run(*, client: str = "ESH", geos=None, **_kwargs):
    """Pipeline CLI entrypoint (ESH-only supply-chain script)."""
    del geos
    if str(client).upper() != "ESH":
        print(f"[skip] supply_chain script is ESH-only (got client={client})")
        return None
    return main()


from config_manager.report_helpers import print_script_completed

if __name__ == "__main__":
    main()
    print_script_completed('all_helper_files')

# conversion stats: custom_split removals=4, sku_mapping swaps=5
