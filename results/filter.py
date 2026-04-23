import pandas as pd

# Input and output file paths
input_file = "satd_fix_detection_2years.xlsx"          # change to your Excel file name
output_file = "SATD_2years_fixed_Final.xlsx"

# Read the Excel file
df = pd.read_excel(input_file)

# Keep only rows where status == "fix_found"
filtered_df = df[df["status"] == "fix_found"]

# Save to a new Excel file
filtered_df.to_excel(output_file, index=False)

print(f"Filtered file saved as: {output_file}")
print(f"Number of kept rows: {len(filtered_df)}")