#change current working directory
import os

#set folderlocation for files
folderloc = ""

#checks if user left folder location blank
if folderloc == "":
    
    print('Please update the fileloc where the program is stored. Press enter to exit.')
    input()
    quit()

#change location for saved files
os.chdir(folderloc)

from Robinhood import Robinhood
from profit_extractor import profit_extractor
import getpass
import collections
import argparse
import ast
import sys
import pandas as pd

logged_in = False

# hard code your credentials here to avoid entering them each time you run the script
username = ""
password = ""

parser = argparse.ArgumentParser(
    description='Export Robinhood trades to a CSV file')
parser.add_argument(
    '--debug', action='store_true', help='store raw JSON output to debug.json')
parser.add_argument(
    '--username', default=username, help='your Robinhood username')
parser.add_argument(
    '--password', default=password, help='your Robinhood password')
parser.add_argument(
    '--mfa_code', help='your Robinhood mfa_code')
parser.add_argument(
    '--profit', action='store_true', help='calculate profit for each sale')
args = parser.parse_args()
username = args.username
password = args.password
mfa_code = args.mfa_code

robinhood = Robinhood()

# login to Robinhood
while logged_in != True:
    if username == "":
        print("Robinhood username:", end=' ')
        try:
            input = raw_input
        except NameError:
            pass
        username = input()
    if password == "":
        password = getpass.getpass()

    logged_in = robinhood.login(username=username, password=password)
    if logged_in != True and logged_in.get('non_field_errors') == None and logged_in['mfa_required'] == True:
        print("Robinhood MFA:", end=' ')
        try:
            input = raw_input
        except NameError:
            pass
        mfa_code = input()
        logged_in = robinhood.login(username=username, password=password, mfa_code=mfa_code)
        
    if logged_in != True:
        password = ""
        print("Invalid username or password.  Try again.\n")

print("Pulling trades. Please wait...")

# fetch transfer history and related metadata from the Robinhood API
transfers = robinhood.get_endpoint('ach_transfers')

# do/while for pagination
paginated = True
page = 0
TransferList = pd.DataFrame()
while paginated:
    
    #create and append transferlist
    TransferList = TransferList.append(pd.DataFrame.from_dict(transfers['results'], orient = 'columns'))
    
    # paginate
    if transfers['next'] is not None:
        page = page + 1
        transfers = robinhood.get_custom_endpoint(str(transfers['next']))
    else:
        paginated = False

#Filename for TransferList
TransferFilename = 'TransferList.csv'

#writes to csv
TransferList.to_csv(TransferFilename)

trade_count = 0
queued_count = 0

# store debug
if args.debug:
    # save the CSV
    try:
        with open("debug.txt", "w+") as outfile:
            outfile.write(str(orders))
            print("Debug infomation written to debug.txt")
    except IOError:
        print('Oops.  Unable to write file to debug.txt')

# fetch order history and related metadata from the Robinhood API
orders = robinhood.get_endpoint('orders')

#Filename for Stored and master file of all transactions 
CleanedMasterTransactionFilename = 'CleanedMasterTransactionList.csv'

#Filename for last transactions 
LastTransactionFilename = 'LastTransaction.csv'

#Filename for new file that will contain updates if any exist
UpdateTransactionFilename = 'UpdateTransactionList.csv'

#Reads in LastTransaction from Orders
LastTransaction = pd.DataFrame.from_dict(orders['results'], orient = 'columns')[0:1] \
                    .astype({'average_price':'float', 'cumulative_quantity':'float', 'fees':'float', 'price':'float' \
                             , 'quantity':'float'}) \
                    .drop(['cancel', 'executions', 'reject_reason', 'stop_price'], axis = 1)

#Checks if MasterTransactionList exists. If not, UpdateTransactionList does not need to be created
if os.path.isfile(CleanedMasterTransactionFilename):
    
    if LastTransaction.equals(pd.read_csv(LastTransactionFilename, index_col=0, nrows = 1)):
        
        #Checks if UpdateTransactionFilename exists.
        if os.path.isfile(UpdateTransactionFilename):    
            
            #prompt user there were no updates, gives option to delete update file
            print("No updates found, would you like to delete the update file? Enter y/n", end=' ')
            try:
                input = raw_input
            except NameError:
                pass
            y_n = input()   
            
            #if user selects yes, UpdateTransactionFile will be deleted
            if y_n == "y":
                
                #deletes the update file
                os.remove(UpdateTransactionFilename)
        else:
            
            #prompt user there were no updates
            print("No updates found, press enter to exit.", end=' ')
            try:
                input = raw_input
            except NameError:
                pass
            input()
            
        sys.exit()
        
    #reads in CleanedMasterTransactionList.csv file date which is the last filled transaction
    LastTransactionDate = pd.read_csv(CleanedMasterTransactionFilename, index_col=0, nrows = 1, parse_dates = ['date']).date[-1]
    
    #Sets UpdateTransaction Indicator to False
    UpdateTransaction = True
    
else:
    
    #Sets UpdateTransaction Indicator to False
    UpdateTransaction = False

# do/while for pagination
paginated = True
page = 0
TransactionList = pd.DataFrame()
while paginated:
    
   
    #creates the executions df by pulling out the executions column from the orders['results']
    #query used to keep index in tact for merging later, only care about state == "filled"
    #removes the empty list values so the dataframe can be merged into the TransactionList dataframe 
    #empty list values are conncurent with cancelled orders
    order = pd.DataFrame.from_dict(orders['results'], orient = 'columns').query('state == "filled"')
    
    #converts to a dataframe and renames id column
    executions = pd.DataFrame([dict(x[0]) for x in order.executions]) \
                                .rename(columns = {'id' : 'exec_id'}) \
                               .set_index(order.index)
    
    #combines the orders and executions dataframes and concats to the TransactionList dataframe
    TransactionList = pd.concat([TransactionList, order.drop(['price','quantity'], axis = 1) \
                                .merge(executions, how = 'inner', left_index = True, right_index = True) \
                                .drop('executions', axis = 1)], ignore_index = True)                                              
    
    # paginate
    if orders['next'] is not None:
        page = page + 1
        orders = robinhood.get_custom_endpoint(str(orders['next']))
    else:
        paginated = False

#convert date to datetime for sorting
TransactionList.timestamp = pd.to_datetime(TransactionList.timestamp, format = '%Y-%m-%dT%H:%M:%S')

#sort by date with most recent at the top
TransactionList = TransactionList.sort_values('timestamp', axis = 0, ascending= True).reset_index(drop= True)

#if UpdateTransaction is True, will select only new records
if UpdateTransaction:
        
    #Finds the last transaction index location        
    LastTransLoc = TransactionList[TransactionList.timestamp == LastTransactionDate].index[0]+1
            
    #resets the dataframe to only contain new info
    TransactionList = TransactionList.iloc[LastTransLoc:]
    
    #set paginated to False to end While Loop
    paginated = False

# check we have trade data to export
if trade_count > 0 or queued_count > 0:
    print("%d queued trade%s and %d executed trade%s found in your account." %
          (queued_count, "s" [queued_count == 1:], trade_count,
           "s" [trade_count == 1:]))
  
#gets symbol information
TransactionList['symbol'] = [robinhood.get_custom_endpoint(x)['symbol'] for x in TransactionList['instrument']]
     
#removes unncessary columns, only looks at filled transactions, and renames fees column to commission
TransactionList = TransactionList[['symbol','side','cumulative_quantity','average_price','fees','timestamp']] \
                        .rename(columns={'side':'action','cumulative_quantity':'shares', \
                                         'timestamp':'date', 'fees':'commission'})

##convert date to datetime for sorting
#TransactionList.date = pd.to_datetime(TransactionList.date, format = '%Y-%m-%dT%H:%M:%S')
#
##sort by date with most recent at the top
#TransactionList = TransactionList.sort_values('date', axis = 0, ascending= False).reset_index(drop= True)

#If UpdateTransaction is False, CleanedMasterTransactionList needs to be created
if UpdateTransaction == False:
    
    # save the CSV
    try:
        TransactionList.to_csv(CleanedMasterTransactionFilename)
    except IOError:
        print("Oops.  Unable to write file to ", CleanedMasterTransactionFilename)
    
#    if args.profit:
#        profit_csv = profit_extractor(csv, CleanedMasterTransactionFilename)


#If MasterTransactionExists is True, UpdateTransactionList needs to be created and appended to MasterTransactionList
else:
    
    #Save UpdateTransactionList as .csv
    TransactionList.to_csv(UpdateTransactionFilename) 
     
    #Appends MasterTransactionList which contains updates to top of CleanedMasterTransactionList
    pd.concat([pd.read_csv(CleanedMasterTransactionFilename, index_col=0), TransactionList], ignore_index = True) \
                .to_csv(CleanedMasterTransactionFilename) 

#Saves LastTransaction for future use
LastTransaction.to_csv(LastTransactionFilename)

#prompt user there were no updates
print("Export completed, press enter to exit.", end=' ')
try:
    input = raw_input
except NameError:
    pass
input()