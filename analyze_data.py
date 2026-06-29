import os
import pandas as pd


def analyze_scraped_data(csv_file: str = "all_products.csv"):

    # Check if file exists
    if not os.path.exists(csv_file):
        print(
            f"❌ Error: '{csv_file}' not found in the current directory! Please make sure the data scraper has generated it."
        )
        return

    # Load CSV
    df = pd.read_csv(csv_file)

    total_rows = len(df)

    print("\n" + "=" * 60)
    print("📊 SCRAPED DATA QUALITY SUMMARY REPORT")
    print("=" * 60)
    print(f"📈 Total Rows (Products) Processed: {total_rows}")
    print("=" * 60)

    # Function to detect empty values (supports strings, NaN, lists, dicts)
    def is_empty(value):
        if pd.isna(value):
            return True
        if value == "":
            return True
        if value == []:
            return True
        if value == {}:
            return True
        return False

    report_data = []

    # Analyze each column
    for column in df.columns:
        total_empty = df[column].apply(is_empty).sum()
        missing_percentage = (total_empty / total_rows) * 100

        report_data.append(
            {
                "Column Name": column,
                "Empty Cells Count": int(total_empty),
                "Missing Percentage": f"{missing_percentage:.2f}%",
            }
        )

    # Convert to DataFrame for clean output
    report_df = pd.DataFrame(report_data)

    print(report_df.to_string(index=False))

    print("=" * 60)
    print("💡 Note: 0.00% means the column is perfect with NO empty data.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    analyze_scraped_data()