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
    load_country_helper,
    mapping_from_convertor_helper,
)
from config_manager import paths as cfg_paths




def main():
    """Converted notebook body (processing logic unchanged)."""
    # --- path roots from .env (no hardcoded OneDrive users) ---
    INV = cfg_paths.esh_inventory_root()
    CENTRAL = cfg_paths.esh_central_root()
    DEMAND_ROOT = cfg_paths.esh_demand_instock_root()  # optional

    # --- notebook cell 1 ---
    import pandas as pd
    import os
    import numpy as np
    import re
    from datetime import datetime
    from datetime import timedelta
    from datetime import date

    # --- notebook cell 2 ---
    from datetime import datetime
    datestr_T= pd.to_datetime("today").strftime("%d-%b-%Y")
    print(datestr_T)

    # --- notebook cell 3 ---
    from datetime import datetime
    datestr= (pd.to_datetime("today") - timedelta(1)).strftime("%d-%b-%Y")
    print(datestr)

    # --- notebook cell 4 ---
    from datetime import datetime
    datestr2= (pd.to_datetime("today") - timedelta(2)).strftime("%d-%b-%Y")
    print(datestr2)

    # --- notebook cell 5 ---
    # Country_helper.xlsx via config_manager (ESH_DATA_ROOT / optional ESH_COUNTRY_HELPER_PATH)
    convertor_main, convertor_helper, convertor = load_country_helper()
    convertor.head(2)

    # --- notebook cell 10 ---
    # New File format
    updike_sellable = pd.read_excel(INV / r"us/input/updike/inventory_balances/WebLink - Item Inventory.xlsx",skipfooter=1)


    # Get the current month and year
    current_month_year = datetime.now().strftime("%b-%Y")

    # Define the saving directory
    saving_directory = INV / r"us/input/updike/inventory_balances/2026/"

    # Create the current month folder if it doesn't exist
    current_month_folder = os.path.join(saving_directory, current_month_year)
    if not os.path.exists(current_month_folder):
        os.makedirs(current_month_folder)

    # Define the filename
    filename = "inventory_" + datestr + ".csv"

    # Define the file path
    file_path = os.path.join(current_month_folder, filename)

    # Save the DataFrame to CSV in the current month folder
    updike_sellable.to_csv(file_path, index=False)

    updike_sellable.head()

    # --- notebook cell 11 ---
    updike_sellable.rename(columns = {'Item' : 'SKU', 'Qty On Hand': 'Updike On Hand',"Qty Available" : "Rectifier_Sellable"}, inplace = True)                
    updike_sellable = updike_sellable.loc[:, ['SKU','Updike On Hand',"Rectifier_Sellable",'Qty Outbound', 'Qty Inbound', 'Qty Projected']]

    

    updike_sellable["Rectifier_Sellable"] =  updike_sellable["Rectifier_Sellable"].fillna(0)
    updike_sellable.head()

    # --- notebook cell 12 ---
    updike_sellable['Rectifier_Sellable'].sum()

    # --- notebook cell 13 ---
    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    updike_sellable = clean_warehouse_sku_column(
        updike_sellable, sku_column="SKU", sku_mapping=sku_mapping
    )

    # Display the updated DF2
    updike_sellable.head(10)

    # --- notebook cell 14 ---
    updike_sellable["Updike On Hand"] = pd.to_numeric(updike_sellable["Updike On Hand"].astype(str).str.replace(',', '', regex=True),errors='coerce')
    updike_sellable["Qty Outbound"] = pd.to_numeric(updike_sellable["Qty Outbound"].astype(str).str.replace(',', '', regex=True),errors='coerce')
    updike_sellable["Qty Projected"] = pd.to_numeric(updike_sellable["Qty Projected"].astype(str).str.replace(',', '', regex=True),errors='coerce')
    updike_sellable["Rectifier_Sellable"] = pd.to_numeric(updike_sellable["Rectifier_Sellable"].astype(str).str.replace(',', '', regex=True),errors='coerce')
    updike_sellable["Qty Inbound"] = pd.to_numeric(updike_sellable["Qty Inbound"].astype(str).str.replace(',', '', regex=True),errors='coerce')

    #updike_sellable["Rectifier_Sellable"] = pd.to_numeric(updike_sellable["Rectifier_Sellable"].str.replace(',', '', regex=True), errors='coerce')

    updike_sellable = pd.pivot_table( updike_sellable,index = 'SKU', values = ['Updike On Hand','Rectifier_Sellable','Qty Outbound', 'Qty Inbound', 'Qty Projected'], aggfunc = 'sum').reset_index() # type: ignore
    updike_sellable.info()
    updike_sellable.head()

    # --- notebook cell 16 ---
    orders = pd.read_excel(INV / r"dashboard_essential_files/WH_Orders_Standard_File.xlsx", sheet_name = "Updike-Orders")

    orders = orders.drop(orders[orders.Updike_Status== "Shipped"].index) 
    orders.reset_index(drop=True, inplace=True)

    orders.head()

    # --- notebook cell 17 ---
    orders.rename(columns = {'Ship_Qty_Updike' : 'Qty Comitted',"Carrier" : "Company"}, inplace = True)      
    orders = orders.loc[:,['SKU', 'Reference_No', 'Company', 'Qty Comitted' ]]       
    orders.head()

    # --- notebook cell 18 ---
    orders['Company'] = np.where(orders['Company'] == 'Shipbob', 'Shipbob Incoming From Updike',
                                 np.where(orders['Company'] == 'Amazon', 'Amazon Incoming From Updike',
                                          np.where(orders['Company'] == 'Updike', 'Updike Internal Shipment',
                                                   np.where(orders['Company'] == 'Walmart', 'Walmart Incoming From Updike',
                                                            'Retail Committed Updike'))))

    orders = pd.pivot_table(orders, index="SKU", columns="Company", values= "Qty Comitted", aggfunc = 'sum').reset_index() # type: ignore

    orders = orders.fillna(0)
    orders.head()

    # --- notebook cell 19 ---
    # For Retail Incoming from Updike__________________________________________________________________________________________________________________________________________________________________________________________________________

    df_new_rows = pd.DataFrame({'SKU' : 'CPC25NL', 'Retail Committed Updike' : 0}, index=[0])
    df_new_row1 = pd.DataFrame({'SKU' : 'CPC25NL', 'Amazon Incoming From Updike' : 0}, index=[0])
    df_new_row2 = pd.DataFrame({'SKU' : 'CPC25NL', 'Shipbob Incoming From Updike' : 0}, index=[0])
    df_new_row3 = pd.DataFrame({'SKU' : 'CPC25NL', 'Walmart Incoming From Updike' : 0}, index=[0])

    samle_dataframe = pd.concat([df_new_rows, df_new_row1, df_new_row2,df_new_row3])

    samle_dataframe = pd.pivot_table(samle_dataframe, index="SKU", values= [ 'Retail Committed Updike','Amazon Incoming From Updike','Shipbob Incoming From Updike', 'Walmart Incoming From Updike'], aggfunc = 'sum').reset_index()

    samle_dataframe = samle_dataframe.fillna(0)
    samle_dataframe.head()

    # --- notebook cell 20 ---
    Orders_Total = pd.concat([orders, samle_dataframe])
    Orders_Total = Orders_Total.fillna(0)
    Orders_Total.head()

    # --- notebook cell 21 ---
    Orders_Total = pd.pivot_table( Orders_Total,index = 'SKU', values = ['Retail Committed Updike','Amazon Incoming From Updike',
                                                                   'Shipbob Incoming From Updike', 
                                                           'Walmart Incoming From Updike'], aggfunc = 'sum').reset_index()
    Orders_Total.head()

    # --- notebook cell 22 ---
    # Merging Updike Inventory with Updike Orders__________________________________________________________________________________________________________________________________________________________________________________________________________
    updike_invnto = pd.merge(updike_sellable, Orders_Total, on = "SKU", how = "outer")

    updike_invnto["Updike Comitted"] = updike_invnto['Amazon Incoming From Updike'] + updike_invnto['Retail Committed Updike'] + updike_invnto['Shipbob Incoming From Updike'] + updike_invnto ['Walmart Incoming From Updike']
    updike_invnto = updike_invnto.fillna(0)
    updike_invnto.tail(2)

    # --- notebook cell 23 ---
    #updike_sellable['Updike On Hand']  = updike_sellable['Qty_Sellable'] + updike_sellable["Updike Comitted"]
    updike_invnto = updike_invnto.astype({'Updike On Hand' : 'float'})

    # --- notebook cell 24 ---
    updike_invnto['Updike Comitted'] = np.where(updike_invnto['Updike Comitted'] == updike_invnto['Qty Outbound'], updike_invnto['Qty Outbound'], updike_invnto['Updike Comitted'])

    updike_invnto['Updike Sellable'] = updike_invnto['Updike On Hand'] - updike_invnto["Updike Comitted"]

    updike_invnto['Updike Sellable'] = np.where(updike_invnto['Updike Sellable'] != updike_invnto['Rectifier_Sellable'], updike_invnto['Rectifier_Sellable'], updike_invnto['Updike Sellable'])

    # --- notebook cell 25 ---
    updike_invnto= updike_invnto.fillna(0)
    updike_invnto.info()
    updike_invnto.head()

    # --- notebook cell 26 ---
    #Exporting Updike Stock Inventory
    updike_invnto['Date'] = (datetime.today()- timedelta(1)).strftime('%d-%b-%Y')
    updike_invnto = pd.merge(updike_invnto, convertor, on ="SKU", how = "left")
    #######################################################################################################
    #updike_invnto["Updike Sellable"] = np.where((updike_invnto['Updike Sellable'] < 0), updike_invnto['Updike On Hand'], updike_invnto['Updike Sellable'])

    #updike_invnto= updike_invnto.rename (columns = {'Qty_Sellable' : 'Updike Sellable'})
    updike_invnto = updike_invnto.drop(updike_invnto[updike_invnto.SKU=="nan"].index)

    updike_invnto.head()

    # --- notebook cell 28 ---
    UDreceipts = pd.read_excel(INV / r"dashboard_essential_files/WH_Receipts_Standard_File.xlsx", sheet_name="Updike-Receipts") 
    UDreceipts.head()

    # --- notebook cell 30 ---
    # BST16/BKDO normalization via esh_sku_cleaning.DEFAULT_SKU_NORMALIZATION
    UDreceipts['Delivery_Date'] = UDreceipts['Delivery_Date'].apply(
        lambda x: pd.to_datetime(x).strftime("%d-%b-%Y") if pd.to_datetime(x, errors='coerce') is not pd.NaT else None)

    UDreceipts_Qty = UDreceipts.iloc[:,[0,2,3,4]]
    UDreceipts_Qty.head()

    # --- notebook cell 32 ---
    UDreceipts_time = UDreceipts.iloc[:,[0,1]]
    UDreceipts_time = UDreceipts_time.drop_duplicates()   
    UDreceipts_time.reset_index(drop=True)

    UDreceipts_time.head()

    # --- notebook cell 34 ---
    containers = pd.read_excel(INV / r"IMS_dashboard/dashboard_international/Container_Data.xlsx", sheet_name ="Container SKU")

    # --- notebook cell 35 ---
    containers.rename(columns = {"US WH Name" :"Warehouse"}, inplace = True)

    def convert_to_date(x):
        try:
            return pd.to_datetime(x).strftime("%d-%b-%Y")
        except (ValueError, TypeError):
            return None

    date_columns = ['Dispatched Date from WH', 'Departure Date from Port', 'Arrival Date on Port']

    for column in date_columns:
        containers[column] = containers[column].apply(convert_to_date)


    containers["Reference_No"] = np.where((containers["Reference_No"]  == 20520750612) & (containers.Container_No == 143),"Cont-#143-20520750612",containers["Reference_No"])
    containers.head()

    # --- notebook cell 37 ---
    containers_updike = containers.loc[:,["Container_No",'Reference_No','Dispatched Date from WH',"Departure Date from Port",
                                   "Arrival Date on Port","Origin",'Destination Port','Main Delivery Date','Status','SKU','Cases','Box/Cases', 'QTY in Box', ]][containers["Warehouse"] == "Updike"]

    containers_Qty = containers_updike.iloc[:,[0,1,9,10,11,12]]
    containers_Qty.head()

    # --- notebook cell 39 ---
    containers_time = containers_updike.iloc[:,[0,1,2,3,4,5,6,7,8]]
    containers_time = containers_time.drop_duplicates()   

    containers_time.head()

    # --- notebook cell 41 ---
    Updk_rect = pd.merge(UDreceipts_Qty,containers_Qty, on=["Reference_No", "SKU"],how = "outer" )
    Updk_rect.rename(columns={ "Received Qty" : 'Received_Updike_C','Cases' :'Shipped_Case', 'QTY in Box' : "Shipped_Box"},inplace = True)
    Updk_rect.head()

    # --- notebook cell 42 ---
    Updk_rect = pd.merge(pd.merge(Updk_rect, UDreceipts_time, on = "Reference_No",  how = "left"),
                         containers_time, on =  ["Reference_No",'Container_No'], how = "left")

    dropping = ('calitrans830', 'TRANSFER')
    Updk_rect = Updk_rect.drop(Updk_rect[Updk_rect.Reference_No.isin(dropping)].index)
    Updk_rect.head()

    # --- notebook cell 43 ---
    Updk_rect.rename(columns={"Delivery_Date" : "U_Process_Date","Main Delivey Date" : "DWHD","Status" : "Ship_Status"},inplace =True)
    Updk_rect = pd.merge(Updk_rect, convertor, on="SKU", how ="left")
    Updk_rect["Received_Updike_C"] = Updk_rect["Received_Updike_C"].fillna(0)
    Updk_rect.head()

    # --- notebook cell 44 ---
    Updk_rect = Updk_rect.astype({'Received_Updike_C' : 'float','Shipped_Case' : 'float','Shipped_Box' : 'float'})

    # --- notebook cell 47 ---
    # Received Box
    Updk_rect ["Rcvd_UPDK_Box"] = Updk_rect ["Received_Updike_C"] * Updk_rect ["Box / Case"]

    # Discrepancy Qty
    Updk_rect["Discrepancy_Case"] = np.where((Updk_rect.Ship_Status=="Awaited") & (Updk_rect.Received_Updike_C==0),0,Updk_rect["Received_Updike_C"] - Updk_rect["Shipped_Case"])
    Updk_rect["Discrepancy_Box"] = np.where((Updk_rect.Ship_Status=="Awaited") & (Updk_rect.Received_Updike_C==0),0,Updk_rect["Rcvd_UPDK_Box"] - Updk_rect["Shipped_Box"])

    # --- notebook cell 49 ---
    Updk_rect = Updk_rect.astype({'Discrepancy_Case' : 'float', 'Discrepancy_Box' : 'float'})
    Updk_rect = Updk_rect.reset_index(drop = True, inplace = False)

    # Container
    Updk_rect["Shipped_$Value_Box"]= Updk_rect["Shipped_Case"] * Updk_rect["Main_WAC"] * Updk_rect ["Box / Case"]

    # Updike
    Updk_rect["Received_$Value_Box"]= Updk_rect["Received_Updike_C"]* Updk_rect["Main_WAC"] * Updk_rect ["Box / Case"]

    # Discrepancy Value
    Updk_rect["Discrepancy$Value"]= Updk_rect["Discrepancy_Box"] * Updk_rect["Main_WAC"]

    # --- notebook cell 51 ---
    error_for = ["Receiving In Progress", "Awaiting Delivery", "Receiving", "Awaited", "AW" ]

    error_not_for = ["Delivered-Samples","Delivered-ThreeG","Delivered-Tradful", "Delivered Untracked-Retail"]


    Updk_rect["Error_Type"] = np.where((Updk_rect["Discrepancy_Box"] < 0), "Surplus",
                                       np.where(((Updk_rect["Discrepancy_Box"] == 0) & (Updk_rect["Ship_Status"] == "Reached")), "Exact",
                                                np.where(((Updk_rect["Discrepancy_Box"] == 0) & (Updk_rect["Ship_Status"].isin(error_for))),"Yet to Receive",
                                                         np.where(((Updk_rect["Discrepancy_Box"] == 0) & (Updk_rect["Ship_Status"].isin(error_not_for))),"Others", "Deficit"))))

    # --- notebook cell 55 ---
    Updk_O1= pd.read_excel(INV / r"dashboard_essential_files/WH_Orders_Standard_File.xlsx",sheet_name = "Updike-Orders")

    # --- notebook cell 56 ---
    #Applying Pivot 
    Updk_O1 = pd.pivot_table(Updk_O1, index=["ORDERNUMBER","Reference_No","Carrier","Updike_Status","Order_Closed_Date","SKU"],values="Ship_Qty_Updike", aggfunc="sum").reset_index()
    Updk_O1.head()

    # --- notebook cell 57 ---
    # BST16/BKDO normalization via esh_sku_cleaning.DEFAULT_SKU_NORMALIZATION
    Updk_O1["Updike_Status"] = np.where((Updk_O1.Order_Closed_Date.isnull()), "Receiving", "Closed")

    Updk_O1.head()

    # --- notebook cell 58 ---
    Updk_O1["Reference_No"] = np.where((Updk_O1.Reference_No == "FBA172JLY7G7"),"FBA172JN8S2C",
                            np.where((Updk_O1.Reference_No == "FBA172JN8S2C"),"FBA172JLY7G7",Updk_O1["Reference_No"]))

    Updk_O1["Reference_No"] = np.where((Updk_O1.Reference_No == "TransferEdison"),"Edison",Updk_O1["Reference_No"])

    Updk_O1['SKU'] =np.where((Updk_O1.Reference_No==872076) & (Updk_O1.SKU=="CBP9RO100"), "CBP9RO20",Updk_O1['SKU'])
    Updk_O1['SKU'] =np.where((Updk_O1.Reference_No==872077) & (Updk_O1.SKU=="CBP9RO100"), "CBP9RO20",Updk_O1['SKU'])
    Updk_O1['SKU'] =np.where((Updk_O1.Reference_No==5980849) & (Updk_O1.SKU=="CBP9RO100"), "CBP9RO20",Updk_O1['SKU'])

    Updk_O1 = Updk_O1.drop(Updk_O1[Updk_O1.Reference_No.isnull()].index) 
    Updk_O1.head()

    # --- notebook cell 60 ---
    Updk_Ord_Qty =  Updk_O1.loc[:,["Reference_No","SKU","Ship_Qty_Updike",'Updike_Status']]
    Updk_Ord_Qty = Updk_Ord_Qty.reset_index(drop = True, inplace = False)
    Updk_Ord_Qty.head()

    # --- notebook cell 62 ---
    Updk_Ord_time =  Updk_O1.loc[:,["Reference_No","ORDERNUMBER","Order_Closed_Date", "Carrier"]]
    Updk_Ord_time = Updk_Ord_time.drop_duplicates()
    Updk_Ord_time = Updk_Ord_time.reset_index(drop = True, inplace = False)
    Updk_Ord_time.head()

    # --- notebook cell 65 ---
    amz_USA_Ship = pd.read_excel(INV / r"dashboard_essential_files/Amazon_shipments-incoming_all_country.xlsx",sheet_name="US")
    amz_CA_Ship = pd.read_excel(INV / r"dashboard_essential_files/Amazon_shipments-incoming_all_country.xlsx",sheet_name="CA")

    # --- notebook cell 66 ---
    amz_ship = pd.concat([amz_USA_Ship,amz_CA_Ship]).reset_index(drop = True)
    amz_ship = amz_ship.loc[:,['Reference No.', 'Amazon Shipment Name', 'Created Date','Received Date', 'Shipment successfully closed', 'Merchant_SKU','Received in Amazon','Expected Qty', 'Status', 'Country']]

    amz_ship.rename(columns={'Reference No.' : 'Reference_No', "Amazon Shipment Name" : "Shipment_name", 'Created Date' : "Created_Date",'Received Date' : 'Received_Date',
                             'Shipment successfully closed' : "Date_Actual_Closed", 'Merchant_SKU' : "SKU",'Received in Amazon' : "Amz_Received_Qty",
                             'Expected Qty' : 'Exptd_Qty', 'Status' : "Amz_Status" }, inplace = True) # type: ignore

    amz_ship = pd.pivot_table(amz_ship, index = ["Reference_No","Shipment_name","Created_Date","Received_Date","Date_Actual_Closed","Amz_Status","SKU","Country"], # type: ignore
                               values = ["Amz_Received_Qty",'Exptd_Qty'], aggfunc = 'sum').reset_index() # type: ignore
    amz_ship["Reference_No"] = np.where((amz_ship["Reference_No"] == "FBA178PYVBR6" ),"FBA178PWHN9F", amz_ship["Reference_No"] )
    amz_ship["From"] = "Amazon"
    amz_ship.head()

    # --- notebook cell 68 ---
    retail_po = pd.read_csv(CENTRAL / r"retail/Retail-Dashboard_Files/retail_po_sku_data.csv")
    retail_po.head()

    # --- notebook cell 69 ---
    retail_po = retail_po[~retail_po.Status.apply(lambda x: str(x).__contains__("Cancelled"))]
    retail_po = retail_po.loc[:,["Distributors","PO_Number", "PO_Requested_Delivery_Date","UPC/GTIN","SKU",
                                 "SKU_Qty","Invoice_Qty", "Status", "Actual Fulfillment Date"]] 

    retail_po["UPC/GTIN"] = retail_po["UPC/GTIN"].fillna(0)
    retail_po["UPC/GTIN"] = (
        retail_po["UPC/GTIN"]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    retail_po.rename(columns = {'PO_Number' : 'Reference_No',"Distributors" : "Shipment_name", "PO_Requested_Delivery_Date" : "Created_Date","Actual Fulfillment Date" : "Date_Actual_Closed"}, inplace = True)       

    #retail_po["Reference_No"] = retail_po.Reference_No.apply(lambda x: x.split("-")[0])
    retail_po["Reference_No"] = retail_po.Reference_No.apply(lambda x: list(reversed(str(x).split('-')))[0])
    retail_po["Reference_No"] = retail_po.Reference_No.apply(lambda x: list(reversed(str(x).split('PO')))[0])
    retail_po["Reference_No"] = retail_po.Reference_No.apply(lambda x: list(reversed(str(x).split('po')))[0])

    # Add a prefix to all column Reference
    prefix = 'PO'
    retail_po.Reference_No = [prefix + col for col in retail_po.Reference_No]

    retail_po["From"] = "Retail"
    retail_po.head()

    # --- notebook cell 71 ---
    Wal = pd.read_excel(INV / r"dashboard_essential_files/Walmart_all_shipment.xlsx")

    # --- notebook cell 72 ---
    Wal.rename(columns = {'PO Number' : 'Reference_No', "PO Create Date" : "Created_Date","PO Delivered Date" : "Date_Actual_Closed", "Reference_SKU" : "SKU", "PO Status" : "Status",
                           "Received Units" : "SKU_Qty","Original PO Number" : "Shipment_name",'Expected Units': 'Exptd_Qty' }, inplace = True)  

    Wal  = Wal.loc[:,["Reference_No","Shipment_name", "SKU","Created_Date" ,"Date_Actual_Closed" , "Status","SKU_Qty",'Exptd_Qty' ]]

    Wal["From"] = "Walmart"

    # Filter out rows with specified values in the 'Status' column
    Wal = Wal[~Wal['Status'].isin(["CANCELLED", 'CANCELLED_GDM', 'PROCESSED_GDM', 'MOVED'])]

    Wal["Status"] = np.where(((Wal["Status"] =="Receiving In Progress" ) | (Wal["Status"] == "RECEIVING_IN_PROGRESS")| (Wal["Status"] == "RECEIVED")),
                              "Receiving", Wal["Status"]) 
    Wal.head()

    # --- notebook cell 74 ---
    shipment = pd.concat([amz_ship,retail_po,Wal ]).reset_index(drop = True)

    # --- notebook cell 75 ---
    def convert_to_date(x):
        try:
            return pd.to_datetime(x).strftime("%d-%b-%Y")
        except (ValueError, TypeError):
            return None

    date_columns = ['Created_Date', 'Received_Date', 'Date_Actual_Closed']

    for column in date_columns:
        shipment[column] = shipment[column].apply(convert_to_date)

    shipment.head()

    # --- notebook cell 76 ---
    shipment["Status"]= np.where((shipment["Amz_Status"].isnull()), shipment["Status"], shipment["Amz_Status"])
    shipment["Received_Qty"]= np.where((shipment["Amz_Received_Qty"].isnull()), shipment["SKU_Qty"], shipment["Amz_Received_Qty"])

    shipment["UPC/GTIN"] = shipment["UPC/GTIN"].fillna(0)

    shipment.drop(columns = ["Amz_Received_Qty","Amz_Status","SKU_Qty","Invoice_Qty" ], inplace = True)

    shipment.head()

    # --- notebook cell 77 ---
    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    shipment = clean_warehouse_sku_column(
        shipment, sku_column="SKU", sku_mapping=sku_mapping, strip_case=False
    )

    shipment['Exptd_Qty'] = shipment['Exptd_Qty'].fillna(shipment['Received_Qty'])

    shipment.head()

    # --- notebook cell 79 ---
    shipment_time = shipment.loc[:,["Reference_No", "Shipment_name","Created_Date", "Received_Date", "Date_Actual_Closed","Country","From",]]
    shipment_time = shipment_time.drop_duplicates()   
    shipment_time.head()

    # --- notebook cell 80 ---
    #merged_df.to_excel(...Downloads...)  # debug export disabled

    # --- notebook cell 81 ---
    # Selecting on Merge dataframes based on "Reference_No" for Updike SLA & Shipment SLA
    Time_dataframe = pd.merge(Updk_Ord_time, shipment_time, on='Reference_No', how='left', indicator=True)

    # --- notebook cell 83 ---
    shipment_qty = pd.pivot_table(shipment, index = ["Reference_No", "SKU",'UPC/GTIN', "Status"],values = ["Received_Qty","Exptd_Qty"], aggfunc = 'sum').reset_index()

    shipment_qty.head(2)

    # --- notebook cell 85 ---
    # Merging Updike Qty & Shipment Qty
    Qty_dataframe = pd.merge(Updk_Ord_Qty, shipment_qty, left_on=["Reference_No","SKU"], right_on=["Reference_No","SKU"], how = "left")
    Qty_dataframe.head(2)

    # --- notebook cell 86 ---
    # Merging on Qty Dataframe & SLA Dataframe

    Updike_outgoing_tracker = pd.merge(Qty_dataframe, Time_dataframe, on="Reference_No", how = "left")
    Updike_outgoing_tracker.head(2)

    # --- notebook cell 87 ---

    Updike_outgoing_tracker["Ship_Qty_Updike"] = np.where(((Updike_outgoing_tracker["Reference_No"] == "2673504GDM" ) & (Updike_outgoing_tracker["Received_Qty"] ==  0 )),
                                                           0, Updike_outgoing_tracker["Ship_Qty_Updike"])

    Updike_outgoing_tracker.head()

    # --- notebook cell 88 ---
    Updike_outgoing_tracker["Status"] = np.where(((Updike_outgoing_tracker["Carrier"] == "Retail") & (Updike_outgoing_tracker["Status"].isnull())), "Delivered Untracked-Retail",
                                         np.where(((Updike_outgoing_tracker["Carrier"] == "Sample") & (Updike_outgoing_tracker["Status"].isnull())), "Delivered-Samples",Updike_outgoing_tracker["Status"]))

    Updike_outgoing_tracker["Status"] = Updike_outgoing_tracker["Status"].fillna("Delivered-"+Updike_outgoing_tracker["Carrier"])

    # --- notebook cell 89 ---
    from datetime import datetime
    addon = (pd.to_datetime("today") + timedelta(20)).strftime("%d-%b-%Y")
    print(addon)

    #Drop Rows
    Updike_outgoing_tracker = Updike_outgoing_tracker.drop(Updike_outgoing_tracker[Updike_outgoing_tracker.Status == "SUSPENDED"].index) 

    Updike_outgoing_tracker["Created_Date"] = Updike_outgoing_tracker["Created_Date"].fillna(Updike_outgoing_tracker ["Order_Closed_Date"])

    Updike_outgoing_tracker["Received_Date"] = Updike_outgoing_tracker["Received_Date"].fillna(Updike_outgoing_tracker ["Created_Date"])

    # Streamlining Actual Process Date
    Updike_outgoing_tracker["Date_Actual_Closed"] = np.where((Updike_outgoing_tracker["Status"].isnull() & Updike_outgoing_tracker["Date_Actual_Closed"].isnull()),  Updike_outgoing_tracker["Order_Closed_Date"],
                                                    np.where( ((Updike_outgoing_tracker["Status"] == "Awaiting Delivery") & (Updike_outgoing_tracker["Carrier"] == "Walmart")),addon,Updike_outgoing_tracker["Date_Actual_Closed"]))

    Updike_outgoing_tracker["Date_Actual_Closed"].fillna(Updike_outgoing_tracker["Received_Date"], inplace=True)

    Updike_outgoing_tracker ["Status"] = np.where((Updike_outgoing_tracker ["Status"] == "Fulfilled"), "Closed",Updike_outgoing_tracker ["Status"] )

    # --- notebook cell 90 ---
    Updike_outgoing_tracker = Updike_outgoing_tracker.astype({'Created_Date' : 'datetime64[ns]','Received_Date' : "datetime64[ns]",
                                              'Order_Closed_Date' : 'datetime64[ns]','Date_Actual_Closed' : "datetime64[ns]"})

    Updike_outgoing_tracker["Ship_Qty_Updike"].fillna(0, inplace=True)
    Updike_outgoing_tracker["Received_Qty"].fillna(0, inplace=True)

    # Merging for box per case & Main_WAC
    Updike_outgoing= pd.merge(Updike_outgoing_tracker,convertor, on = "SKU", how = "left" )

    # --- notebook cell 92 ---
    Updike_outgoing ["Ship_Qty_Box"] = Updike_outgoing ["Ship_Qty_Updike"] * Updike_outgoing ["Box / Case"]

    # --- notebook cell 93 ---
    # Sorting Disccrepancy qty based on Status
    intransit = ["Receiving","In transit",'Delivered-Samples','Delivered-ThreeG','Delivered Untracked-Retail', 'Delivered-Tradful']

    closed = ['Delivered-Walmart','Delivered-Amazon','Closed','Short Shipped']

    Updike_outgoing ["Discrepancy_Qty"] = np.where((Updike_outgoing["Status"].isin(intransit)),0,Updike_outgoing ["Received_Qty"] - Updike_outgoing ["Ship_Qty_Box"] )

    # --- notebook cell 94 ---
    # Updike
    Updike_outgoing["Shipped_$Value_Box"]= Updike_outgoing["Ship_Qty_Box"] * Updike_outgoing["Main_WAC"]

    # Amazon
    Updike_outgoing["Received_$Value_Box"]= Updike_outgoing["Received_Qty"]* Updike_outgoing["Main_WAC"]

    # Discrepancy
    Updike_outgoing["Discrepancy$Value"]= Updike_outgoing["Discrepancy_Qty"] * Updike_outgoing["Main_WAC"]

    # Use the apply method with abs() for Discrepancy$Value columns
    Updike_outgoing["Discrepancy$Value"] = Updike_outgoing["Discrepancy$Value"].apply(abs) # type: ignore

    # --- notebook cell 96 ---
    error_for = ["Receiving In Progress", "Awaiting Delivery", "Receiving" ]

    error_not_for = ["Delivered-Samples","Delivered-ThreeG","Delivered-Tradful", "Delivered Untracked-Retail"]


    Updike_outgoing["Error_Type"] = np.where((Updike_outgoing["Discrepancy_Qty"] > 0), "Surplus",
                                       np.where(((Updike_outgoing["Discrepancy_Qty"] == 0) & (Updike_outgoing["Status"] == "Closed")), "Exact",
                                                np.where(((Updike_outgoing["Discrepancy_Qty"] == 0) & (Updike_outgoing["Status"].isin(error_for))),"Yet to Receive",
                                                         np.where(((Updike_outgoing["Discrepancy_Qty"] == 0) & (Updike_outgoing["Status"].isin(error_not_for))),"Others", "Deficit"))))

    # --- notebook cell 98 ---
    updike_invnto.head(2)

    # --- notebook cell 99 ---
    #WH Value
    updike_invnto["$Sellable"] =  updike_invnto["Updike Sellable"] * updike_invnto["Box / Case"] * updike_invnto["Main_WAC"]

    updike_invnto["$On_Hand"] =  updike_invnto["Updike On Hand"] * updike_invnto["Box / Case"] * updike_invnto["Main_WAC"]

    updike_invnto["$Amazon"] =  updike_invnto["Amazon Incoming From Updike"] * updike_invnto["Box / Case"] * updike_invnto["Main_WAC"]

    updike_invnto["$Retail"] =  updike_invnto["Retail Committed Updike"] * updike_invnto["Box / Case"] * updike_invnto["Main_WAC"]

    updike_invnto["$Walmart"] =  updike_invnto["Walmart Incoming From Updike"] * updike_invnto["Box / Case"] * updike_invnto["Main_WAC"]

    updike_invnto["$Shipbob"] =  updike_invnto["Shipbob Incoming From Updike"] * updike_invnto["Box / Case"] * updike_invnto["Main_WAC"]

    updike_invnto["$Reserved"] =  updike_invnto["Updike Comitted"] * updike_invnto["Box / Case"] * updike_invnto["Main_WAC"]

    # --- notebook cell 100 ---
    # Saving Updike Database file for New Dashboard

    with pd.ExcelWriter(INV / r"IMS_new_Dashboard_files/USA-Updike_WH.xlsx") as writer:
        Updk_rect.to_excel(writer, sheet_name = "Updike_Rect", index = False)
        Updike_outgoing.to_excel(writer, sheet_name = "Updk-Outgoing", index = False)
        updike_invnto.to_excel(writer, sheet_name = "Updk-Inveto", index = False)

    # --- notebook cell 101 ---
    import os
    from datetime import datetime

    # Get the current month and year
    current_month_year = datetime.now().strftime("%b-%Y")

    # Define the saving directory
    saving_directory = INV / r"Output_Database/USA/Updike/2026/"

    # Create the current month folder if it doesn't exist
    current_month_folder = os.path.join(saving_directory, current_month_year)
    if not os.path.exists(current_month_folder):
        os.makedirs(current_month_folder)

    # Define the file path
    file_path = os.path.join(current_month_folder, "Updike_WH_Database_" + datestr + ".xlsx")

    # Export the Excel file
    with pd.ExcelWriter(file_path) as writer:
        Updk_rect.to_excel(writer, sheet_name = "Updike_Rect", index = False)
        Updike_outgoing.to_excel(writer, sheet_name = "Updk-Outgoing", index = False)
        updike_invnto.to_excel(writer, sheet_name = "Updk-Inveto", index = False)

    # --- notebook cell 106 ---
    three_sell = pd.read_excel(INV / r"us/input/3G/stock_status_report/stock_status_report.xlsx", header = 6)
    three_sell.head(2)

    # --- notebook cell 107 ---
    import os
    from datetime import datetime

    # Get the current month and year
    current_month_year = datetime.now().strftime("%b-%Y")

    # Define the saving directory
    saving_directory = INV / r"us/input/3G/stock_status_report/2026/"

    # Create the current month folder if it doesn't exist
    current_month_folder = os.path.join(saving_directory, current_month_year)
    if not os.path.exists(current_month_folder):
        os.makedirs(current_month_folder)

    # Define the filename
    filename = "stock_status_report_" + datestr + ".xlsx"

    # Define the file path
    file_path = os.path.join(current_month_folder, filename)

    # Save the DataFrame to CSV in the current month folder
    three_sell.to_excel(file_path, index=False)

    # --- notebook cell 108 ---
    three_sell = three_sell.iloc[:,[0,10,15,11,19]]
    three_sell = three_sell.drop(three_sell[three_sell.UOM== "Each"].index) 
    three_sell.info()
    three_sell.head()

    # --- notebook cell 109 ---
    three_sell['Allocated_Cal'] = three_sell['OnHand'] - three_sell['Available']
    # Apply your initial lambda function to handle 'amzn.gr.'
    three_sell['SKU'] = three_sell['SKU'].apply(lambda x: list(reversed(str(x).split('amzn.gr.')))[0])

    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    three_sell = clean_warehouse_sku_column(
        three_sell, sku_column="SKU", sku_mapping=sku_mapping
    )

    # Display the updated DF2
    threeG = pd.pivot_table( three_sell,index = ['SKU'],values = ['OnHand',	'Available','Allocated','Allocated_Cal'], aggfunc = 'sum').reset_index() # type: ignore
    threeG.head()

    # --- notebook cell 110 ---
    threeG.rename(columns={"OnHand" : "3G On Hand", "Available" :"3G Fulfillable" ,"Allocated" :"3G Committed", 'Sku': 'SKU'}, inplace =True)
    threeG = threeG[threeG["SKU"].str.contains("NaN") == False]
    threeG["3G On Hand"] = threeG["3G On Hand"].fillna(0)
    threeG["3G Fulfillable"] = threeG["3G Fulfillable"].fillna(0)
    threeG["3G Committed"] = threeG["3G Committed"].fillna(0)
    threeG = threeG.astype({'3G On Hand' : 'float','3G Fulfillable' : 'float','3G Committed' : 'float'})
    threeG = threeG.loc[:, ['SKU', '3G On Hand', '3G Committed', '3G Fulfillable','Allocated_Cal']]
    threeG = threeG.drop(threeG[threeG.SKU == 'nan'].index)
    threeG.info()

    # --- notebook cell 112 ---
    outgoing = pd.read_excel(INV / r"dashboard_essential_files/WH_Orders_Standard_File.xlsx", sheet_name = "3G-Orders")
    outgoing.info()

    # --- notebook cell 113 ---
    outgoing = outgoing.drop(outgoing[outgoing['3G_Status']== "Closed"].index) 
    outgoing

    # --- notebook cell 115 ---
    #For Amazon Order Incoming from 3G____________________________________________________________________________________________________________________________________________________________________________

    incom_amz =outgoing.loc[:, ['SKU','ShipToCountry','Qty','Company']][outgoing.Company == "Amazon"]
    incom_amz = incom_amz.reset_index(drop = True, inplace = False)
    incom_amz= incom_amz.rename (columns = {'Qty' : 'Amazon'}) # type: ignore
    # Create a new row and add it to the DataFrame
    df_new_rows = pd.DataFrame({'SKU': ['CPC25NL'], 'Amazon': [0]})
    incom_amz = pd.concat([incom_amz, df_new_rows], ignore_index=True)
    incom_amz.head()

    # --- notebook cell 116 ---
    # Pivot the DataFrame
    incom_amz = pd.pivot_table(incom_amz, index='SKU', columns='ShipToCountry', values='Amazon', aggfunc='sum').reset_index() # type: ignore
    incom_amz = incom_amz.fillna(0)
    incom_amz.head(2)

    # --- notebook cell 117 ---
    if 'US' not in incom_amz.columns:
        incom_amz['US'] = 0

    # --- notebook cell 118 ---
    if 'CA' not in incom_amz.columns:
        incom_amz['CA'] = 0

    # --- notebook cell 119 ---
    # Aggregate the "Amazon Incoming From 3G" values for CA and US
    incom_amz["Amazon"] = incom_amz["CA"] + incom_amz["US"]
    # Display the resulting DataFrame

    incom_amz.rename (columns = {"CA" : "3G_to_Amazon_CA", "US" : "3G_to_Amazon_US" }, inplace = True)

    incom_amz.head()

    # --- notebook cell 121 ---
    #For Retail Order Incoming from 3G____________________________________________________________________________________________________________________________________________________________________________

    incom_retail =outgoing.loc[:, ['SKU','ShipToCountry','Qty','Company']][outgoing.Company == "Retail"]
    incom_retail = incom_retail.reset_index(drop = True, inplace = False)
    incom_retail= incom_retail.rename (columns = {'Qty' : 'Retail'}) # type: ignore

    df_new_rows = pd.DataFrame({'SKU' : 'CPC25NL', 'Retail' : 0}, index=[0])
    incom_retail = pd.concat([incom_retail, df_new_rows])

    incom_retail = pd.pivot_table( incom_retail,index = 'SKU', values = ['Retail'], aggfunc = 'sum').reset_index()
    incom_retail.head()

    # --- notebook cell 123 ---
    #For Samples Order Incoming from 3G____________________________________________________________________________________________________________________________________________________________________________

    incom_samples =outgoing.loc[:, ['SKU','ShipToCountry','Qty','Company']][outgoing.Company == "Samples"]
    incom_samples = incom_samples.reset_index(drop = True, inplace = False)
    incom_samples= incom_samples.rename (columns = {'Qty' : 'Samples'}) # type: ignore

    df_new_rows = pd.DataFrame({'SKU' : 'CPC25NL', 'Samples' : 0}, index=[0])
    incom_samples = pd.concat([incom_samples, df_new_rows])

    incom_samples = pd.pivot_table( incom_samples,index = 'SKU', values = ['Samples'], aggfunc = 'sum').reset_index()
    incom_samples.head()

    # --- notebook cell 125 ---
    #For Walmart Order Incoming from 3G____________________________________________________________________________________________________________________________________________________________________________

    incom_Walmart =outgoing.loc[:, ['SKU','ShipToCountry','Qty','Company']][outgoing.Company == "Walmart"]
    incom_Walmart = incom_Walmart.reset_index(drop = True, inplace = False)
    incom_Walmart= incom_Walmart.rename (columns = {'Qty' : 'Walmart'}) # type: ignore

    df_new_rows = pd.DataFrame({'SKU' : 'CPC25NL', 'Walmart' : 0}, index=[0])
    incom_Walmart = pd.concat([incom_Walmart, df_new_rows])

    incom_Walmart = pd.pivot_table( incom_Walmart,index = 'SKU', values = ['Walmart'], aggfunc = 'sum').reset_index()
    incom_Walmart.head()

    # --- notebook cell 127 ---
    #For Tradefull Order Incoming from 3G____________________________________________________________________________________________________________________________________________________________________________

    incom_Tradefull =outgoing.loc[:, ['SKU','ShipToCountry','Qty','Company']][outgoing.Company == "Tradefull"]
    incom_Tradefull = incom_Tradefull.reset_index(drop = True, inplace = False)
    incom_Tradefull= incom_Tradefull.rename (columns = {'Qty' : 'Tradefull'}) # type: ignore

    df_new_rows = pd.DataFrame({'SKU' : 'CPC25NL', 'Tradefull' : 0}, index=[0])
    incom_Tradefull = pd.concat([incom_Tradefull, df_new_rows])

    incom_Tradefull = pd.pivot_table( incom_Tradefull,index = 'SKU', values = ['Tradefull'], aggfunc = 'sum').reset_index()
    incom_Tradefull.head()

    # --- notebook cell 129 ---
    #For Shipbob Order Incoming from 3G____________________________________________________________________________________________________________________________________________________________________________

    incom_Shipbob =outgoing.loc[:, ['SKU','ShipToCountry','Qty','Company']][outgoing.Company == "Shipbob"]
    incom_Shipbob = incom_Shipbob.reset_index(drop = True, inplace = False)
    incom_Shipbob= incom_Shipbob.rename (columns = {'Qty' : 'Shipbob'}) # type: ignore

    df_new_rows = pd.DataFrame({'SKU' : 'CPC25NL', 'Shipbob' : 0}, index=[0])
    incom_Shipbob = pd.concat([incom_Shipbob, df_new_rows])

    incom_Shipbob = pd.pivot_table( incom_Shipbob,index = 'SKU', values = ['Shipbob'], aggfunc = 'sum').reset_index()
    incom_Shipbob.head()

    # --- notebook cell 130 ---
    # List of dataframes to merge
    open_orders  = pd.merge(pd.merge(pd.merge(pd.merge(pd.merge(incom_amz,incom_retail, on='SKU', how='outer'),
                                incom_samples, on='SKU', how='outer'),
                                incom_Walmart, on='SKU', how='outer'),
                                incom_Tradefull, on='SKU', how='outer'),
                                incom_Shipbob, on='SKU', how='outer')
    open_orders = open_orders.fillna(0)
    open_orders.head()

    # --- notebook cell 131 ---
    # Merging 3G Inventory & 3G Orders__________________________________________________________________________________________________________________________________________________________________________________________________________________________
    ThreeGstock = pd.merge(threeG, open_orders, on = "SKU", how = "outer")
    ThreeGstock = ThreeGstock.fillna(0)
    ThreeGstock.head(2)

    # --- notebook cell 132 ---
    ThreeGstock["KIT"] = ThreeGstock.SKU.apply(lambda x: ["KIT" if x.lower().__contains__("kit") else 0][0])
    #Saving 3g todays inventory file
    ThreeG_invnto= ThreeGstock
    ThreeG_invnto['Date'] = (datetime.today()- timedelta(1)).strftime('%d-%b-%Y')
    ThreeG_invnto = pd.merge(ThreeG_invnto, convertor, on ="SKU", how = "left")

    ThreeG_invnto.to_csv(INV / r"us/output/3G/cleaned_inventory/3G_stock.csv", index = False)

    ThreeG_invnto.head(2)

    # --- notebook cell 133 ---
    # 3G WH Value
    ThreeG_invnto["$Sellable_Box"] =  ThreeG_invnto["3G Fulfillable"] * ThreeG_invnto["Box / Case"] * ThreeG_invnto["Main_WAC"]

    ThreeG_invnto["$On_Hand_Box"] =  ThreeG_invnto["3G On Hand"] * ThreeG_invnto["Box / Case"] * ThreeG_invnto["Main_WAC"]

    ThreeG_invnto["$Amazon_Box"] =  ThreeG_invnto["Amazon"] * ThreeG_invnto["Box / Case"] * ThreeG_invnto["Main_WAC"]

    ThreeG_invnto["$Retail_Box"] =  ThreeG_invnto["Retail"] * ThreeG_invnto["Box / Case"] * ThreeG_invnto["Main_WAC"]

    ThreeG_invnto["$Walmart_Box"] =  ThreeG_invnto["Walmart"] * ThreeG_invnto["Box / Case"] * ThreeG_invnto["Main_WAC"]

    ThreeG_invnto["$Shipbob_Box"] =  ThreeG_invnto["Shipbob"] * ThreeG_invnto["Box / Case"] * ThreeG_invnto["Main_WAC"]

    ThreeG_invnto["$Tradefull_Box"] =  ThreeG_invnto["Tradefull"] * ThreeG_invnto["Box / Case"] * ThreeG_invnto["Main_WAC"]

    ThreeG_invnto["$Sample_Box"] =  ThreeG_invnto["Samples"] * ThreeG_invnto["Box / Case"] * ThreeG_invnto["Main_WAC"]

    ThreeG_invnto["$Reserved_Box"] =  ThreeG_invnto["3G Committed"] * ThreeG_invnto["Box / Case"] * ThreeG_invnto["Main_WAC"]

    ThreeG_invnto.head()

    # --- notebook cell 136 ---
    rect = pd.read_excel(INV / r"dashboard_essential_files/WH_Receipts_Standard_File.xlsx",sheet_name="3G-Receipts")
    rect.head()

    # --- notebook cell 138 ---
    rect_time= rect.loc[:, ["TID","Reference_No","Creation_3G","Arrival_3G", "Notes"]]
    rect_time = rect_time.drop_duplicates()   
    rect_time.reset_index(drop=True)

    rect_time.head()

    # --- notebook cell 140 ---
    rect_qty = rect.loc[:, ["Reference_No", "SKU","Qty"]]

    # Reset the index
    rect_qty = rect_qty.reset_index(drop=True)

    # Display the head of the DataFrame
    rect_qty.head()

    # --- notebook cell 141 ---
    # Apply your initial lambda function to handle 'amzn.gr.'
    rect_qty['SKU'] = rect_qty['SKU'].apply(lambda x: list(reversed(str(x).split('amzn.gr.')))[0])

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
    rect_qty.head()

    # --- notebook cell 143 ---
    containers_3G = pd.read_excel(INV / r"IMS_new_Dashboard_files\Container_Data.xlsx",sheet_name='Container SKU')
    containers_3G.rename(columns = {"US WH Name" :"Warehouse"}, inplace = True)
    warehouse_pick = ["AMAZON & 3G", "3G"]
    containers_3G = containers_3G.loc[:,["Container_No",'Reference_No','Dispatched Date from WH',"Departure Date from Port",
                                   "Arrival Date on Port","Origin",'Destination Port','Main Delivery Date','Status','SKU','Cases','Box/Cases', 'QTY in Box', ]][containers_3G["Warehouse"].isin(warehouse_pick)]

    containers_3G["Reference_No"] = np.where((containers_3G["Reference_No"] == 36984052975) & (containers_3G.Container_No==97),"CON36984052975",containers_3G["Reference_No"])
    containers_3G["Cases"] = np.where((containers_3G["Reference_No"] == "CSNU7189494") & (containers_3G.SKU =="PLB6RO100"),"30",containers_3G["Cases"])

    containers_3G["SKU"] = np.where(((containers_3G.SKU =="PLPB8&10SQ200") | (containers_3G.SKU =="PLPB8+10SQ200")),"PLPB7&10SQ200",containers_3G["SKU"])   
    containers_3G["SKU"] = np.where(((containers_3G.SKU =="PLPB8&10SQ50") | (containers_3G.SKU =="PLPB8+10SQ50")),"PLPB7&10SQ50",containers_3G["SKU"])
    containers_3G["SKU"] = np.where(((containers_3G.SKU =="PLPB8&10SQ100") | (containers_3G.SKU =="PLPB8+10SQ100")),"PLPB7&10SQ100",containers_3G["SKU"])
    containers_3G.head()

    # --- notebook cell 145 ---
    containers_3G_Qty = containers_3G.loc[:,['Container_No','Reference_No','SKU','Cases','Box/Cases','QTY in Box']]
    containers_3G_Qty.head()

    # --- notebook cell 147 ---
    containers_3G_time = containers_3G.loc[:,['Container_No','Reference_No','Dispatched Date from WH','Departure Date from Port','Arrival Date on Port','Origin','Destination Port',
                                               'Main Delivery Date','Status']]
    containers_3G_time = containers_3G_time.drop_duplicates()   

    containers_3G_time.head()

    # --- notebook cell 149 ---
    ThreeG_rect = pd.merge(rect_qty,containers_3G_Qty, on =["Reference_No", "SKU"], how = "outer" )
    ThreeG_rect["Qty"] = ThreeG_rect["Qty"].fillna(0)
    ThreeG_rect.head()

    # --- notebook cell 151 ---
    ThreeG_rect = pd.merge(ThreeG_rect,containers_3G_time, on =["Reference_No",'Container_No'], how = "outer")
    ThreeG_rect.head()

    # --- notebook cell 152 ---
    ThreeG_rect = pd.merge(ThreeG_rect, rect_time, on ="Reference_No", how = "outer")
    ThreeG_rect = pd.merge(ThreeG_rect, convertor, on = "SKU", how = "left")
    #ThreeG_rect = ThreeG_rect.drop(["Container_No_y"], axis=1)
    ThreeG_rect.head()

    # --- notebook cell 153 ---
    ThreeG_rect = ThreeG_rect.astype({'Cases' : 'float', 'Dispatched Date from WH' : 'datetime64[ns]', 'Departure Date from Port' : 'datetime64[ns]', 'Arrival Date on Port' : 'datetime64[ns]',
                                      'Main Delivery Date' : 'datetime64[ns]' })
    ThreeG_rect.info()

    # --- notebook cell 156 ---
    ThreeG_rect["Difference_Cases"]= np.where((ThreeG_rect.Status != "Reached"),0,ThreeG_rect["Qty"] - ThreeG_rect["Cases"])

    ThreeG_rect["Shipped_Value_Cases"]= ThreeG_rect["Cases"] * ThreeG_rect["Main_WAC"] * ThreeG_rect['Box / Case']
    ThreeG_rect["Received_Value_Cases"]= ThreeG_rect["Qty"] * ThreeG_rect["Main_WAC"] * ThreeG_rect['Box / Case']
    ThreeG_rect["Discrepancy_$Value"]= np.where((ThreeG_rect['Status']!="Reached"),0, ThreeG_rect["Difference_Cases"] * ThreeG_rect["Main_WAC"] * ThreeG_rect['Box / Case'])

    # --- notebook cell 158 ---
    ThreeG_rect["Error_Type"] = np.where(((ThreeG_rect["Difference_Cases"] == 0) & (ThreeG_rect["Status"] == "Reached")), "Exact",
                                                np.where(((ThreeG_rect["Difference_Cases"] > 0) & (ThreeG_rect["Status"] == "Reached")),"Surplus",
                                                         np.where(((ThreeG_rect["Difference_Cases"] < 0) & (ThreeG_rect["Status"] == "Reached")), "Deficit", "Awaited" )))

    # --- notebook cell 162 ---
    incoming = pd.read_excel(INV / r"dashboard_essential_files/WH_Orders_Standard_File.xlsx",sheet_name="3G-Orders")

    incoming.rename (columns = {'Qty': 'Qty_out_3G'}, inplace = True)

    incoming.head()

    # --- notebook cell 164 ---
    threeG_orders_time = incoming.loc[:,['Reference_No','OrderId', 'Company', 'Tracking No.','3G_Status', 'PoNum', 'Creation_Date', 'Closed_Date', 'ShipToCountry']]

    threeG_orders_time = threeG_orders_time.drop_duplicates()  
    threeG_orders_time.reset_index(drop=True)

    threeG_orders_time.head()

    # --- notebook cell 166 ---
    rectifier = threeG_orders_time.loc[:,["Reference_No", 'PoNum']]
    rectifier.head(2)

    # --- notebook cell 168 ---
    threeG_orders_qty = incoming.loc[:,['Reference_No','PoNum','SKU','Qty_out_3G']]
    threeG_orders_qty.head()

    # --- notebook cell 171 ---
    amazon_reci= pd.read_excel(INV / r"dashboard_essential_files/Amazon_shipments-incoming_all_country.xlsx",sheet_name= 'US')

    # --- notebook cell 172 ---

    amazon_reci.rename(columns={"Reference No." : "Reference_No",'Created Date' : "CH_Date_Created", "Merchant_SKU" : "SKU", "Amazon Shipment Name" : "Shipment_Name",
                                "Received Date" : "Date_RCVD_Amazon","Shipment successfully closed" : "CH_Date_Actual_Closed","Received in Amazon" : "RCVD_Qty",
                                'Status' : 'CH_Status',"Expected Qty" : "Exp_Qty" },inplace = True)

    amazon_reci.head()

    # --- notebook cell 173 ---

    #amazon_reci.SKU = amazon_reci.SKU.apply(lambda x: list(reversed(x.split('amzn.gr.')))[0])
    amazon_reci.SKU = amazon_reci.SKU.apply(lambda x: str(x).split('-New')[0])

    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    amazon_reci = clean_warehouse_sku_column(
        amazon_reci, sku_column="SKU", sku_mapping=sku_mapping
    )

    #Applying rectifier to select coommon reference no.
    amazon_reci = pd.merge(rectifier, amazon_reci, on="Reference_No", how = "inner")
    amazon_reci.head()

    # --- notebook cell 175 ---
    amazon_reci_qty = amazon_reci.loc[:,['Reference_No','SKU','RCVD_Qty', 'Exp_Qty']]
    amazon_reci_qty.head()

    # --- notebook cell 177 ---
    amazon_reci_time = amazon_reci.loc[:,['Reference_No','Shipment_Name','CH_Date_Created', 'Date_RCVD_Amazon', 'CH_Date_Actual_Closed', 'CH_Status' ]]
    amazon_reci_time["Channel"] = "Amazon"
    amazon_reci_time.reset_index(drop=True)
    amazon_reci_time = amazon_reci_time.drop_duplicates()  
    amazon_reci_time.head()

    # --- notebook cell 178 ---
    amazon_reci_time['CH_Date_Created'] = np.where(amazon_reci_time['CH_Date_Created'].astype(str).str.contains('-'),
             pd.to_datetime(amazon_reci_time['CH_Date_Created']).dt.strftime('%d-%b-%Y'), # type: ignore
             pd.to_datetime(amazon_reci_time['CH_Date_Created'], dayfirst=False).dt.strftime('%d-%b-%Y')) # type: ignore

    amazon_reci_time['Date_RCVD_Amazon'] = np.where(amazon_reci_time['Date_RCVD_Amazon'].astype(str).str.contains('-'),
             pd.to_datetime(amazon_reci_time['Date_RCVD_Amazon']).dt.strftime('%d-%b-%Y'), # type: ignore
             pd.to_datetime(amazon_reci_time['Date_RCVD_Amazon'], dayfirst=False).dt.strftime('%d-%b-%Y')) # type: ignore

    amazon_reci_time['CH_Date_Actual_Closed'] = np.where(amazon_reci_time['CH_Date_Actual_Closed'].astype(str).str.contains('-'),
             pd.to_datetime(amazon_reci_time['CH_Date_Actual_Closed']).dt.strftime('%d-%b-%Y'), # type: ignore
             pd.to_datetime(amazon_reci_time['CH_Date_Actual_Closed'], dayfirst=False).dt.strftime('%d-%b-%Y')) # type: ignore

    amazon_reci_time.head()

    # --- notebook cell 180 ---
    retail_po = pd.read_csv(CENTRAL / r"retail/Retail-Dashboard_Files/retail_po_sku_data.csv")

    # --- notebook cell 181 ---
    retail_po = retail_po[~retail_po.Status.apply(lambda x: str(x).__contains__("Cancelled"))]
    retail_po = retail_po.loc[:,["Distributors","PO_Number", "PO_Requested_Delivery_Date","UPC/GTIN","SKU", "SKU_Qty","Invoice_Qty", "Status", "Actual Fulfillment Date"]] 
    retail_po["UPC/GTIN"] = retail_po["UPC/GTIN"].fillna(0)
    retail_po["UPC/GTIN"] = (
        retail_po["UPC/GTIN"]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    retail_po.head()

    # --- notebook cell 182 ---
    retail_po.rename(columns = {'PO_Number' : 'PoNum', "SKUs" : "SKU", "Status" : 'CH_Status', 'Invoice_Qty' : 'Exp_Qty','SKU_Qty' : 'RCVD_Qty',
                                 'Actual Fulfillment Date' : 'CH_Date_Actual_Closed', 'PO_Requested_Delivery_Date' : 'CH_Date_Created' }, inplace = True)   # type: ignore

    retail_po = pd.pivot_table(retail_po, index = ["Distributors","PoNum","CH_Date_Created", # type: ignore
                                                   "CH_Date_Actual_Closed","UPC/GTIN","SKU","CH_Status"], values = ["RCVD_Qty","Exp_Qty"], aggfunc = 'sum').reset_index() # type: ignore

    retail_po["Channel"] = "Retail"
    retail_po.head()

    # --- notebook cell 183 ---
    # Condition : Split PoNum on '-'
    retail_po["PoNum"] = retail_po.PoNum.apply(lambda x: x.split("-")[0])
    retail_po["PoNum"] = np.where((retail_po["PoNum"]=='MX'),'PO460EDES23',retail_po["PoNum"])
    # Condition : Add prefix 'PO' if PoNum is numeric
    retail_po['PoNum'] = retail_po['PoNum'].apply(lambda x: f'PO{x}' if str(x).isnumeric() else x)

    #Applying rectifier to select coommon reference no.
    retail_po = pd.merge(rectifier, retail_po, on="PoNum", how = "inner")
    retail_po.head()

    # --- notebook cell 185 ---
    retail_po_time = retail_po.loc[:,['Distributors','PoNum','CH_Date_Created', 'CH_Date_Actual_Closed', 'CH_Status','Channel']]
    retail_po_time.reset_index(drop=True)
    retail_po_time = retail_po_time.drop_duplicates()  

    retail_po_time['CH_Date_Created'] = np.where(retail_po_time['CH_Date_Created'].astype(str).str.contains('-'),
             pd.to_datetime(retail_po_time['CH_Date_Created']).dt.strftime('%d-%b-%Y'), # type: ignore
             pd.to_datetime(retail_po_time['CH_Date_Created'], dayfirst=False).dt.strftime('%d-%b-%Y')) # type: ignore

    retail_po_time['CH_Date_Actual_Closed'] = np.where(retail_po_time['CH_Date_Actual_Closed'].astype(str).str.contains('-'),
             pd.to_datetime(retail_po_time['CH_Date_Actual_Closed']).dt.strftime('%d-%b-%Y'), # type: ignore
             pd.to_datetime(retail_po_time['CH_Date_Actual_Closed'], dayfirst=False).dt.strftime('%d-%b-%Y')) # type: ignore
    retail_po_time.head()

    # --- notebook cell 187 ---
    retail_po_qty = retail_po.loc[:,['PoNum','SKU','UPC/GTIN','Exp_Qty', 'RCVD_Qty' ]]
    retail_po_qty.head()

    # --- notebook cell 189 ---
    walrecep = pd.read_excel(INV / r"dashboard_essential_files/Walmart_all_shipment.xlsx")

    # --- notebook cell 190 ---
    walrecep.rename (columns = {"PO Number" : 'PoNum',"PO Status":"CH_Status","PO Delivered Date":"CH_Date_Actual_Closed","PO Create Date":"CH_Date_Created",
                                "Expected Units": "Exp_Qty", "Received Units" : "RCVD_Qty", "GTIN" :"UPC/GTIN" }, inplace = True)

    walrecep.head().head()

    # --- notebook cell 191 ---
    # Import Helper file
    Wal_help = pd.read_excel(CENTRAL / r"Task file\Helper.xlsx",sheet_name='Walmart')

    # --- notebook cell 192 ---

    Wal_help.rename (columns = {"Reference No.- WH" : "Reference No.", 
                                 "Base SKU":"SKU"}, inplace = True)
    Wal_help.head()

    # --- notebook cell 193 ---
    walmart_df = pd.merge(walrecep, Wal_help,  left_on = ["PoNum","SKU"], right_on= ["Reference No.","Reference_SKU"],how = "left")
    walmart_df.head(2)

    # --- notebook cell 194 ---
    walmart_df["SKU"] = np.where((walmart_df["SKU_y"].isnull()), walmart_df["SKU_x"], walmart_df["SKU_y"])
    walmart_df["Quantity"] = walmart_df["Quantity"].fillna(1)

    walmart_df["Exp_Qty"] = walmart_df["Exp_Qty"]*walmart_df["Quantity"]
    walmart_df["RCVD_Qty"] = walmart_df["RCVD_Qty"]*walmart_df["Quantity"]

    walmart_df["CH_Status"] = np.where((walmart_df["Status"]=="Send"), walmart_df["CH_Status"],walmart_df["Status"] )

    # --- notebook cell 195 ---
    #Drop extra columns
    dropping_wal_unwanted = ["Original PO Number",'Reference No.', 'Description', 'SKU_x', 'Reference_SKU', 'SKU_y', 'Shipment ID- Walmart', 'Status',
                             'Checked in units at ICC','Damaged Units', 'Qty_New', 'Quantity','UPC']
    walmart_df.drop(columns=dropping_wal_unwanted, inplace=True)

    #Drop blank Rows
    walmart_df = walmart_df.drop(walmart_df[walmart_df["PoNum"].isnull()].index) 

    walmart_df['Channel'] = 'Walmart'

    #Applying rectifier to select coommon reference no.
    walmart_df = pd.merge(rectifier, walmart_df, on="PoNum", how = "inner")
    walmart_df.head()

    # --- notebook cell 197 ---
    walmart_df_qty = walmart_df.loc[:,['PoNum','SKU','UPC/GTIN','Exp_Qty', 'RCVD_Qty' ]]
    walmart_df_qty.head()

    # --- notebook cell 199 ---
    walmart_df_time = walmart_df.loc[:,['PoNum','Inbound Order ID','CH_Date_Created', 'CH_Date_Actual_Closed', 'CH_Status','Channel']]
    walmart_df_time.reset_index(drop=True)
    walmart_df_time = walmart_df_time.drop_duplicates()  

    walmart_df_time['CH_Date_Created'] = np.where(walmart_df_time['CH_Date_Created'].astype(str).str.contains('-'),
             pd.to_datetime(walmart_df_time['CH_Date_Created']).dt.strftime('%d-%b-%Y'), # type: ignore
             pd.to_datetime(walmart_df_time['CH_Date_Created'], dayfirst=False).dt.strftime('%d-%b-%Y')) # type: ignore

    walmart_df_time['CH_Date_Actual_Closed'] = np.where(walmart_df_time['CH_Date_Actual_Closed'].astype(str).str.contains('-'),
             pd.to_datetime(walmart_df_time['CH_Date_Actual_Closed']).dt.strftime('%d-%b-%Y'), # type: ignore
             pd.to_datetime(walmart_df_time['CH_Date_Actual_Closed'], dayfirst=False).dt.strftime('%d-%b-%Y')) # type: ignore
    walmart_df_time.head()

    # --- notebook cell 200 ---
    threeG_orders_qty.rename (columns = {"Qty":"Ship_Qty_3G"}, inplace = True) # type: ignore
    threeG_orders_qty["Source"] = "3G"
    threeG_orders_qty.head()

    # --- notebook cell 203 ---
    # Merging 3G order & Amazon (in terms of Qty)
    theeG_out_qty_AMZ = pd.merge(threeG_orders_qty, amazon_reci_qty, left_on=["Reference_No","SKU"], right_on=["Reference_No","SKU"], how = "left")

    # Merging 3G time in main dataframe
    theeG_out_df1 = pd.merge(theeG_out_qty_AMZ,threeG_orders_time, on=["Reference_No","PoNum"], how = "left")

    # Merging Amazon time dataframe in theeG_out_df1
    theeG_out_df1 = pd.merge(theeG_out_df1,amazon_reci_time, on="Reference_No", how = "left")

    # dropping rows where company != Amazon
    theeG_out_df1 = theeG_out_df1.drop(theeG_out_df1[theeG_out_df1.Company!= "Amazon"].index)

    theeG_out_df1 = theeG_out_df1.drop(theeG_out_df1[theeG_out_df1.Reference_No== "TEB9addon"].index)

    theeG_out_df1.head()

    # --- notebook cell 205 ---
    # Merging 3G order & Retail (in terms of Qty)
    theeG_out_qty_retail = pd.merge(threeG_orders_qty, retail_po_qty, on=["PoNum","SKU"], how = "left")

    # Merging 3G TIME_________& Retail TIME_____________ in main dataframe
    theeG_out_df2 = pd.merge(pd.merge(theeG_out_qty_retail,threeG_orders_time, on=["Reference_No","PoNum"], how = "left"),retail_po_time, on="PoNum", how = "left")

    # dropping rows where company != Retail
    theeG_out_df2 = theeG_out_df2.drop(theeG_out_df2[theeG_out_df2.Company!= "Retail"].index)

    theeG_out_df2.head()

    # --- notebook cell 207 ---
    # Merging 3G order & Walmart (in terms of Qty)
    theeG_out_qty_wal = pd.merge(threeG_orders_qty, walmart_df_qty, on=["PoNum","SKU"], how = "left")

    # Merging 3G TIME_________& Walmart TIME_____________ in main dataframe
    theeG_out_df3 = pd.merge(pd.merge(theeG_out_qty_wal,threeG_orders_time, on=["Reference_No","PoNum"], how = "left"),walmart_df_time, on="PoNum", how = "left")

    # dropping rows where company != Walmart
    theeG_out_df3 = theeG_out_df3.drop(theeG_out_df3[theeG_out_df3.Company!= "Walmart"].index)

    theeG_out_df3.head()

    # --- notebook cell 209 ---
    company_drop = ["Walmart", "Retail" , "Amazon"]

    theeG_out_df4 = pd.merge(theeG_out_qty_wal,threeG_orders_time, on=["Reference_No","PoNum"], how = "left")

    theeG_out_df4 = theeG_out_df4.drop(theeG_out_df4[theeG_out_df4.Company.isin(company_drop)].index)
    theeG_out_df4.head()

    # --- notebook cell 211 ---
    # concating all channel qty except amazon
    DF_main = pd.concat([theeG_out_df1,theeG_out_df2, theeG_out_df3, theeG_out_df4]).reset_index(drop = True)
    DF_main.head()

    # --- notebook cell 212 ---
    DF_main["RCVD_Qty"] = np.where((DF_main.RCVD_Qty.isnull() & DF_main.Company == "Samples" ), DF_main["Qty_out_3G"],DF_main["RCVD_Qty"])
    DF_main["RCVD_Qty"] = DF_main["RCVD_Qty"].fillna(0)
    DF_main["Exp_Qty"] = DF_main["Exp_Qty"].fillna(0)

    # --- notebook cell 214 ---
    DF_main = pd.merge(DF_main, convertor, on = "SKU", how ="left")

    #Creating 3G Box Qty column
    DF_main["ship_Box_3G"] = DF_main["Qty_out_3G"] * DF_main["Box / Case"]

    DF_main = DF_main.drop(DF_main[DF_main.SKU== "RS1"].index)
    DF_main.head()

    # --- notebook cell 216 ---
    ageing = pd.read_excel(INV / r"us/input/3G/inventory_ageing/inventory_ageing.xlsx",header=8, skipfooter=2)
    ageing.rename(columns = {'Unnamed: 0' : 'SKU','Unnamed: 2' : 'On Hand', 'Unnamed: 3': 'Available', 'Unnamed: 4': 'Allocated'}, inplace = True)

    #saving raw file
    ageing.to_excel(INV / r"us/input/3G/inventory_ageing/2026/Jan-2026/inventory_ageing_"+datestr+".xlsx",index = False)
    ageing.head()

    # --- notebook cell 217 ---
    from datetime import datetime
    ageing['Date']= (datetime.today() - timedelta(1)).strftime('%d-%b-%Y')

    ageing['Date'] = ageing['Date'].apply(
        lambda x: pd.to_datetime(x).strftime("%d-%b-%Y") if pd.to_datetime(x, errors='coerce') is not pd.NaT else None)

    ageing.rename(columns = {'8-30' : '30 Days'}, inplace = True)

    ageing = ageing.loc[:,['Date', 'SKU','On Hand', 'Available', 'Allocated',
                        '<= 7','30 Days','31-60','61-90','91-120','121-150','151-180','181-365','1yr-2yr',
                        '2yr-3yr','+3yr']]
    ageing["Report"] = "Ageing"
    ageing.head()

    # --- notebook cell 219 ---
    import os
    from datetime import datetime

    # Get the current month and year
    current_month_year = datetime.now().strftime("%b-%Y")

    # Define the saving directory
    saving_directory = INV / r"Output_Database/USA/3G/2026/"

    # Create the current month folder if it doesn't exist
    current_month_folder = os.path.join(saving_directory, current_month_year)
    if not os.path.exists(current_month_folder):
        os.makedirs(current_month_folder)

    # Define the file path
    file_path = os.path.join(current_month_folder, "3G_WH_Database_" + datestr + ".xlsx")

    # Export the Excel file
    with pd.ExcelWriter(file_path) as writer:
        ThreeG_rect.to_excel(writer, sheet_name = "3G-Receipts", index = False)
        DF_main.to_excel(writer, sheet_name = "3G-Orders", index = False)
        ThreeG_invnto.to_excel(writer, sheet_name = "3G-Inventory", index = False)
        ageing.to_excel(writer, sheet_name = "3G-Aging", index = False)

    # --- notebook cell 220 ---
    # exporting 3G all Database files for New-Dashboard

    with pd.ExcelWriter(INV / r"IMS_new_Dashboard_files/USA-3G_WH.xlsx") as writer:
        ThreeG_rect.to_excel(writer, sheet_name = "3G-Receipts", index = False)
        DF_main.to_excel(writer, sheet_name = "3G-Orders", index = False)
        ThreeG_invnto.to_excel(writer, sheet_name = "3G-Inventory", index = False)
        ageing.to_excel(writer, sheet_name = "3G-Aging", index = False)

    # --- notebook cell 224 ---
    checklist1 = ThreeG_invnto.loc[:,['SKU','3G Fulfillable','Box / Case','3G On Hand', '3G Committed']]
    checklist1['sellable'] = checklist1['Box / Case']  * checklist1['3G Fulfillable']
    checklist1['sellable'].sum()

    # --- notebook cell 225 ---
    checklist1['3G On Hand'].sum()

    # --- notebook cell 226 ---
    checklist1['3G Fulfillable'].sum()

    # --- notebook cell 227 ---
    checklist1['3G Committed'].sum()

    # --- notebook cell 229 ---
    checklist2 = updike_invnto.loc[:,['SKU','Updike On Hand','Updike Sellable','Box / Case','Updike Comitted']]
    checklist2['sellable'] = checklist2['Box / Case']  * checklist2['Updike Sellable']
    checklist2['sellable'].sum()

    # --- notebook cell 230 ---
    updike_sellable['Updike On Hand'].sum() == checklist2['Updike On Hand'].sum()

    # --- notebook cell 231 ---
    checklist2['Updike Sellable'].sum()

    # --- notebook cell 232 ---
    checklist2['Updike Comitted'].sum()


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
    print_script_completed('threeG_nd_updike')

# conversion stats: custom_split removals=5, sku_mapping swaps=5
