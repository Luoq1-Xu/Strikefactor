import requests
import csv
import json
import os

# Use the API for a specific academic year for reproducibility
NUSMODS_API_URL = "https://api.nusmods.com/v2/2025-2026/moduleInfo.json"
OUTPUT_CSV_FILE = "nus_modules.csv"

def download_and_process_modules():
    """
    Fetches module data from the NUSMods API, processes it to match the
    Supabase table structure, and saves it to a CSV file.
    """
    print(f"Attempting to download module data from {NUSMODS_API_URL}...")
    
    try:
        response = requests.get(NUSMODS_API_URL)
        # Raise an exception for bad status codes (4xx or 5xx)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to retrieve modules. Error: {e}")
        return

    print("Download successful. Processing data...")
    modules_data = response.json()

    # Define the headers for your CSV file, matching the Supabase table columns.
    # We exclude 'id' and 'created_at' as Supabase handles them automatically.
    headers = [
        "moduleCode", "title", "description", "moduleCredit", "workload",
        "preclusion", "preclusionRule", "prerequisite", "prerequisiteRule",
        "attributes", "fufillRequirements", "prereqTree", "corequisite",
        "corequisiteRule", "prerequisiteAdvisory", "aliases"
    ]

    processed_rows = []
    for module in modules_data:
        # Convert complex objects/lists to JSON strings for jsonb/text columns
        workload_json = json.dumps(module.get("workload")) if module.get("workload") else None
        prereq_tree_json = json.dumps(module.get("prereqTree")) if module.get("prereqTree") else None
        attributes_json = json.dumps(module.get("attributes")) if module.get("attributes") else None
        
        # Convert lists to comma-separated strings for text columns
        fulfill_reqs_str = ", ".join(module.get("fulfillRequirements", [])) if module.get("fulfillRequirements") else None
        aliases_str = ", ".join(module.get("aliases", [])) if module.get("aliases") else None

        row = {
            "moduleCode": module.get("moduleCode"),
            "title": module.get("title"),
            "description": module.get("description"),
            "moduleCredit": module.get("moduleCredit"),
            "workload": workload_json,
            "preclusion": module.get("preclusion"),
            "prerequisite": module.get("prerequisite"),
            "corequisite": module.get("corequisite"),
            "prereqTree": prereq_tree_json,
            "attributes": attributes_json,
            "fufillRequirements": fulfill_reqs_str,
            "aliases": aliases_str,
            # These fields are in your table but not common in the API response,
            # so we default them to None.
            "preclusionRule": module.get("preclusionRule"),
            "prerequisiteRule": module.get("prerequisiteRule"),
            "corequisiteRule": module.get("corequisiteRule"),
            "prerequisiteAdvisory": module.get("prerequisiteAdvisory")
        }
        processed_rows.append(row)

    # Write the processed data to a CSV file
    try:
        with open(OUTPUT_CSV_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()
            writer.writerows(processed_rows)
        print(f"Successfully saved {len(processed_rows)} modules to {os.path.abspath(OUTPUT_CSV_FILE)}")
    except IOError as e:
        print(f"Error writing to CSV file. Error: {e}")

if __name__ == "__main__":
    download_and_process_modules()