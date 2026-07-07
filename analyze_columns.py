import pandas as pd

df = pd.read_csv("motors_used_cars.csv")
columns = set(df.columns)
print(columns)
#uri
#_highlightResult
#seo_links
#uuid, added
#photos, tags, category_v2
#photo_thumbnails, objectID, category_slug_tree, lookup_attributes, highlighted_ad, details_v2
#details
col_to_check = ['is_inspected', 'has_variants', 'business', 'has_phone_number', 
                'is_featured_agent', 'condition', 'seller_type', 'content_type', 
                'photos_approved', 'can_chat', 'is_cotw_booked', 'is_reserved', 
                'inventory_type', 'has_photos', 'price_type', 'has_vin', 'motors_variant', 
                'is_cotd_booked', 'vas', 'is_super_ad', 'has_any_verification', 'is_export_car', 
                'has_view360', 'stock_level', 'is_premium', 'car_condition', 'cotd_on', 
                'has_sms_number','age', 'has_whatsapp_number', '_distinctSeqID', 'is_spotlight_ad',
                'has_video_url', 'discount_percentage', 'is_verified_business', 'max_quantity', 
                'pre_discount_price', 'is_ecommerce_listing', 'photos_count', 'is_coming_soon', 
                'available_quantity', 'usage', 'listing_group_id', 'is_verified_user', 
                'seller_account_type', '', 'language', 'multi_site']

for col in col_to_check:
    if col in df.columns:
        counts_str = df[col].value_counts(dropna=False).to_string()
        print(counts_str)

#print(df['salaryType'].value_counts())


#print(df[df['canEdit']== True]['id'].head())
#print(df[df['canEdit']== False]['id'].head())

"""columns = ['rentType']
for col in columns:
    if col in df.columns:
        counts_str = df[col].value_counts(dropna=False).to_string()
        print(counts_str)

print("rentType = 1")
print(df[df['rentType'] == 1]['uri'].head())

print("rentType = 3")
print(df[df['rentType'] == 3]['uri'].head())

print("rentType = None")
print(df[df['rentType'] == None]['uri'].head())

print("rentType = 4")
print(df[df['rentType'] == 4]['uri'].head())

print("rentType = 2")
print(df[df['rentType'] == 2]['uri'].head())

print("rentType = 0")
print(df[df['rentType'] == 0]['uri'].head())"""


columns = ['has360', 'moveUpFee', 'promotedFee', 'isService', 'language', 'platform',
           'isBusiness', 'advertisedFor', 'isDeleted', 'condition', 'type', 'status', 'endStatus',
		   'forView', 'fee', 'isExpired', 'isSold', 'hasLive', 'isActiveCategory', 'isFavourite',
		   'isMyProduct', 'isMyWinner', 'isUpdated', 'tag', 'hasPendingUpdate', 'hasActiveVersion',
           'hasPendingPrice', 'pinFee', 'isPinned', 'durationIndex', 'duration', 'isHasMore', 'bidRate',
           'buyNowAmount', 'neededCredit', 'isWon', 'inStudio', 'isDemo', 'isActive', 'isStarted',
           'canComplain', 'isPromoted', 'returnOriginalImages', 'isPinnedToShowroom', 'hasCoverImages',
           'isLocked', 'isBuyNow', 'showroomIsHidden', 'highestBid', 'rejectedMsg']
#highestBid	highestBidder	highestBidderId	history

"""with open("cars_value_counts.txt", "w", encoding="utf-8") as file:
    for col in columns:
        # Check if column exists in the DataFrame to avoid errors
        if col in df.columns:
            file.write(f"\n── {col} ──\n")
            
            # Convert value counts output to string and write to file
            counts_str = df[col].value_counts(dropna=False).to_string()
            file.write(counts_str)
            
            # Add a separator line between columns
            file.write("\n" + "="*40 + "\n")

print("Report saved successfully to cars_value_counts.txt")
"""
"""from datetime import datetime, timedelta, timezone
import pandas as pd

df['date_parsed'] = pd.to_datetime(df['startDate'],format='ISO8601', utc=True)

yesterday = datetime.now(timezone.utc).date() - timedelta(days=2)
print(yesterday)

mask = df['date_parsed'].dt.date == yesterday
df_yesterday = df[mask]

print(f"Number of adds yesterday: {len(df_yesterday)}")

print(df['date_parsed'].dt.date.value_counts().sort_index())"""