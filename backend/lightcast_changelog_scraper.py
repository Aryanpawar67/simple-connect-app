#!/usr/bin/env python3
"""
Lightcast Skills Taxonomy Changelog Scraper
============================================
This script scrapes the complete changelog from Lightcast's documentation
and exports it to a structured Excel file with full analysis.

Author: Python Automation Engineer
Date: 2025-11-26
Updated: 2026-01-07 - Added interactive CLI for date filtering
"""

import re
import time
import base64
import os
from io import BytesIO
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import calendar

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


class LightcastChangelogScraper:
    """
    Scraper for Lightcast Skills Taxonomy Changelog.
    Extracts all monthly updates and structures them into a pandas DataFrame.
    """

    def __init__(self, url: str, date_filter: Optional[List[str]] = None, version_filter: Optional[List[str]] = None):
        """
        Initialize the scraper with the target URL.

        Args:
            url: The changelog URL to scrape
            date_filter: Optional list of month-year strings to filter (e.g., ['2025-11', '2025-12'])
            version_filter: Optional list of version strings to filter (e.g., ['9.39', '9.38'])
        """
        self.url = url
        self.soup = None
        self.raw_data = []
        self.df = None
        self.date_filter = date_filter
        self.version_filter = version_filter

    def fetch_page(self) -> bool:
        """
        Fetch the changelog page using Playwright (handles JavaScript rendering).

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print(f"🌐 Fetching changelog from: {self.url}")
            print("🚀 Launching browser with Playwright...")

            with sync_playwright() as p:
                # Launch browser (headless mode)
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                # Navigate to the page
                print("📄 Loading page content...")
                page.goto(self.url, wait_until="networkidle", timeout=60000)

                # Wait for content to load (adjust selector as needed)
                print("⏳ Waiting for content to render...")
                time.sleep(5)  # Give extra time for dynamic content

                # Get the rendered HTML
                html_content = page.content()

                # Close browser
                browser.close()

                # Parse with BeautifulSoup
                self.soup = BeautifulSoup(html_content, 'html.parser')
                print(f"✅ Page fetched successfully ({len(html_content)} bytes)")
                return True

        except Exception as e:
            print(f"❌ Error fetching page: {e}")
            return False

    def parse_month_year(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse month and year from header text.

        Args:
            text: Header text containing month/year (e.g., "9.37 (November 11, 2025)" or "July 2025")

        Returns:
            Tuple of (month_year_display, month_year_sortable)
        """
        # Match patterns like "9.37 (November 11, 2025)" - version with date in parentheses
        paren_pattern = r'\(([A-Za-z]+)\s+\d+,\s+(\d{4})\)'
        match = re.search(paren_pattern, text)

        if match:
            month_name = match.group(1)
            year = match.group(2)
            month_year_display = f"{month_name} {year}"

            # Convert to sortable format
            try:
                dt = datetime.strptime(month_year_display, "%B %Y")
                month_year_sortable = dt.strftime("%Y-%m")
            except ValueError:
                try:
                    dt = datetime.strptime(month_year_display, "%b %Y")
                    month_year_sortable = dt.strftime("%Y-%m")
                except ValueError:
                    month_year_sortable = f"{year}-{month_name}"

            return month_year_display, month_year_sortable

        # Match patterns like "July 2025", "2025-07", etc.
        month_year_pattern = r'([A-Za-z]+)\s+(\d{4})'
        match = re.search(month_year_pattern, text)

        if match:
            month_name = match.group(1)
            year = match.group(2)
            month_year_display = f"{month_name} {year}"

            # Convert to sortable format
            try:
                dt = datetime.strptime(month_year_display, "%B %Y")
                month_year_sortable = dt.strftime("%Y-%m")
            except ValueError:
                try:
                    dt = datetime.strptime(month_year_display, "%b %Y")
                    month_year_sortable = dt.strftime("%Y-%m")
                except ValueError:
                    month_year_sortable = f"{year}-{month_name}"

            return month_year_display, month_year_sortable

        return None, None

    def parse_version(self, text: str) -> Optional[str]:
        """
        Extract version number from text.

        Args:
            text: Text potentially containing version

        Returns:
            Version string or None
        """
        version_pattern = r'v?(\d+\.\d+(?:\.\d+)?)'
        match = re.search(version_pattern, text, re.IGNORECASE)

        if match:
            return f"v{match.group(1)}"

        return None

    def clean_skill_text(self, text: str) -> str:
        """
        Clean skill name by removing bullets, extra whitespace, and formatting.

        Args:
            text: Raw skill text

        Returns:
            Cleaned skill name
        """
        # Remove bullet points and common list markers
        text = re.sub(r'^[\s\-\*\•\◦\▪\▫\–\—]+', '', text)

        # Remove extra whitespace
        text = ' '.join(text.split())

        # Remove surrounding quotes if present
        text = text.strip('\'"')

        return text.strip()

    def parse_renamed_skill(self, text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Parse renamed skill entries that contain arrows or similar indicators.

        Args:
            text: Skill text potentially containing rename information

        Returns:
            Tuple of (original_name, new_name, notes)
        """
        # Common rename patterns: "Old → New", "Old -> New", "Old renamed to New"
        arrow_patterns = [
            r'(.+?)\s*→\s*(.+)',
            r'(.+?)\s*->\s*(.+)',
            r'(.+?)\s+renamed\s+to\s+(.+)',
            r'(.+?)\s+changed\s+to\s+(.+)',
        ]

        for pattern in arrow_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                original = self.clean_skill_text(match.group(1))
                new = self.clean_skill_text(match.group(2))

                # Check for notes in parentheses
                notes_match = re.search(r'\(([^)]+)\)', text)
                notes = notes_match.group(1) if notes_match else None

                return original, new, notes

        return None, None, None

    def extract_notes(self, text: str) -> Tuple[str, Optional[str]]:
        """
        Extract notes from skill text (usually in parentheses).

        Args:
            text: Skill text

        Returns:
            Tuple of (text_without_notes, notes)
        """
        notes_match = re.search(r'\(([^)]+)\)$', text)

        if notes_match:
            notes = notes_match.group(1)
            text_without_notes = text[:notes_match.start()].strip()
            return text_without_notes, notes

        return text, None

    def parse_changelog_section(self, section) -> List[Dict]:
        """
        Parse a single changelog section (one month's updates).

        Args:
            section: BeautifulSoup element containing the section

        Returns:
            List of dictionaries containing parsed data
        """
        entries = []

        # Find the month/year header
        header = section.find(['h1', 'h2', 'h3', 'h4'])
        if not header:
            return entries

        header_text = header.get_text(strip=True)
        month_year_display, month_year_sortable = self.parse_month_year(header_text)
        version = self.parse_version(header_text)

        if not month_year_display:
            print(f"⚠️  Could not parse month/year from: {header_text}")
            return entries

        print(f"📅 Processing: {month_year_display} {version if version else ''}")

        # Find all h3 category headers in this section
        for h3 in section.find_all('h3'):
            category = h3.get_text(strip=True)

            # Skip internal-only sections if desired (or include them)
            # if 'internal' in category.lower():
            #     continue

            # Find all tab divs and UL lists after this h3 until the next h2/h3
            current = h3.next_sibling
            while current:
                # Stop at next h2 or h3
                if hasattr(current, 'name') and current.name in ['h2', 'h3']:
                    break

                # Look for divs with data-tab attribute or direct UL elements
                if hasattr(current, 'name'):
                    if current.name == 'div':
                        # Check for tab divs
                        tab_divs = current.find_all('div', attrs={'data-tab': True}, recursive=True)
                        for tab_div in tab_divs:
                            tab_name = tab_div.get('data-tab', '')
                            change_type = f"{category} - {tab_name}" if tab_name else category

                            # Find all UL in this tab div
                            for ul in tab_div.find_all('ul', recursive=False):
                                for li in ul.find_all('li', recursive=False):
                                    skill_text = li.get_text(strip=True)
                                    if not skill_text:
                                        continue

                                    # Parse based on change type
                                    if 'rename' in change_type.lower():
                                        # Look for "Renamed X to Y" pattern
                                        renamed_match = re.search(r'Renamed\s+["\']?(.+?)["\']?\s+to\s+["\']?(.+?)["\']?$', skill_text, re.IGNORECASE)
                                        if renamed_match:
                                            original = self.clean_skill_text(renamed_match.group(1))
                                            new = self.clean_skill_text(renamed_match.group(2))
                                            entries.append({
                                                'Month_Year_Display': month_year_display,
                                                'Month_Year_Sortable': month_year_sortable,
                                                'Version': version or '',
                                                'Change_Type': 'Renamed',
                                                'Skill_Name': new,
                                                'Original_Name': original,
                                                'Notes': ''
                                            })
                                        else:
                                            # Fallback
                                            entries.append({
                                                'Month_Year_Display': month_year_display,
                                                'Month_Year_Sortable': month_year_sortable,
                                                'Version': version or '',
                                                'Change_Type': change_type,
                                                'Skill_Name': self.clean_skill_text(skill_text),
                                                'Original_Name': '',
                                                'Notes': ''
                                            })
                                    elif 'consolidation' in change_type.lower():
                                        # Look for "Consolidated X into Y" pattern
                                        consol_match = re.search(r'Consolidated\s+["\']?(.+?)["\']?\s+into\s+["\']?(.+?)["\']?$', skill_text, re.IGNORECASE)
                                        if consol_match:
                                            original = self.clean_skill_text(consol_match.group(1))
                                            new = self.clean_skill_text(consol_match.group(2))
                                            entries.append({
                                                'Month_Year_Display': month_year_display,
                                                'Month_Year_Sortable': month_year_sortable,
                                                'Version': version or '',
                                                'Change_Type': 'Consolidated',
                                                'Skill_Name': new,
                                                'Original_Name': original,
                                                'Notes': ''
                                            })
                                        else:
                                            entries.append({
                                                'Month_Year_Display': month_year_display,
                                                'Month_Year_Sortable': month_year_sortable,
                                                'Version': version or '',
                                                'Change_Type': change_type,
                                                'Skill_Name': self.clean_skill_text(skill_text),
                                                'Original_Name': '',
                                                'Notes': ''
                                            })
                                    else:
                                        # Simple entry (Added, Removed, Tagging Changes, etc.)
                                        entries.append({
                                            'Month_Year_Display': month_year_display,
                                            'Month_Year_Sortable': month_year_sortable,
                                            'Version': version or '',
                                            'Change_Type': change_type,
                                            'Skill_Name': self.clean_skill_text(skill_text),
                                            'Original_Name': '',
                                            'Notes': ''
                                        })

                current = current.next_sibling

        print(f"  ✓ Extracted {len(entries)} entries")
        return entries

    def scrape_all_sections(self) -> bool:
        """
        Scrape all changelog sections from the page.

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.soup:
            print("❌ No page content available. Call fetch_page() first.")
            return False

        print("\n🔍 Parsing changelog sections...")

        # Find all h2 headers with version/date info
        h2_headers = []
        for h2 in self.soup.find_all('h2'):
            h2_text = h2.get_text(strip=True)
            if re.search(r'\d+\.\d+\s*\([A-Za-z]+\s+\d+,\s+\d{4}\)', h2_text):
                h2_headers.append(h2)

        if not h2_headers:
            print("❌ No version headers found.")
            return False

        print(f"📦 Found {len(h2_headers)} version sections to process\n")

        # Process each h2 section
        for h2 in h2_headers:
            header_text = h2.get_text(strip=True)
            month_year_display, month_year_sortable = self.parse_month_year(header_text)
            version = self.parse_version(header_text)

            if not month_year_display:
                print(f"⚠️  Could not parse month/year from: {header_text}")
                continue

            print(f"📅 Processing: {month_year_display} {version if version else ''}")

            # Find all h3 sections after this h2 until the next h2
            current = h2.next_sibling
            entries_in_section = 0

            while current:
                # Stop at next h2
                if hasattr(current, 'name') and current.name == 'h2':
                    break

                # Look for h3 headers (Changed, Added, Removed, etc.)
                if hasattr(current, 'name') and current.name == 'h3':
                    category = current.get_text(strip=True)

                    # Find the tabs div that follows this h3
                    tabs_sibling = current.next_sibling
                    while tabs_sibling:
                        if hasattr(tabs_sibling, 'name'):
                            if tabs_sibling.name in ['h2', 'h3']:
                                break
                            if tabs_sibling.name == 'div' and 'tabs' in tabs_sibling.get('class', []):
                                # Found the tabs container!
                                tab_divs = tabs_sibling.find_all('div', attrs={'data-tab': True}, recursive=False)
                                for tab_div in tab_divs:
                                    tab_name = tab_div.get('data-tab', '')
                                    change_type = f"{category} - {tab_name}" if tab_name else category

                                    # Find all UL in this tab div
                                    for ul in tab_div.find_all('ul', recursive=False):
                                        for li in ul.find_all('li', recursive=False):
                                            skill_text = li.get_text(strip=True)
                                            if not skill_text:
                                                continue

                                            # Parse based on change type
                                            if 'rename' in tab_name.lower():
                                                renamed_match = re.search(r'Renamed\s+(.+?)\s+to\s+(.+?)$', skill_text, re.IGNORECASE)
                                                if renamed_match:
                                                    original = self.clean_skill_text(renamed_match.group(1))
                                                    new = self.clean_skill_text(renamed_match.group(2))
                                                    self.raw_data.append({
                                                        'Month_Year_Display': month_year_display,
                                                        'Month_Year_Sortable': month_year_sortable,
                                                        'Version': version or '',
                                                        'Change_Type': 'Renamed',
                                                        'Skill_Name': new,
                                                        'Original_Name': original,
                                                        'Notes': ''
                                                    })
                                                    entries_in_section += 1
                                                else:
                                                    self.raw_data.append({
                                                        'Month_Year_Display': month_year_display,
                                                        'Month_Year_Sortable': month_year_sortable,
                                                        'Version': version or '',
                                                        'Change_Type': change_type,
                                                        'Skill_Name': self.clean_skill_text(skill_text),
                                                        'Original_Name': '',
                                                        'Notes': ''
                                                    })
                                                    entries_in_section += 1
                                            elif 'consolidation' in tab_name.lower():
                                                consol_match = re.search(r'Consolidated\s+(.+?)\s+into\s+(.+?)$', skill_text, re.IGNORECASE)
                                                if consol_match:
                                                    original = self.clean_skill_text(consol_match.group(1))
                                                    new = self.clean_skill_text(consol_match.group(2))
                                                    self.raw_data.append({
                                                        'Month_Year_Display': month_year_display,
                                                        'Month_Year_Sortable': month_year_sortable,
                                                        'Version': version or '',
                                                        'Change_Type': 'Consolidated',
                                                        'Skill_Name': new,
                                                        'Original_Name': original,
                                                        'Notes': ''
                                                    })
                                                    entries_in_section += 1
                                                else:
                                                    self.raw_data.append({
                                                        'Month_Year_Display': month_year_display,
                                                        'Month_Year_Sortable': month_year_sortable,
                                                        'Version': version or '',
                                                        'Change_Type': change_type,
                                                        'Skill_Name': self.clean_skill_text(skill_text),
                                                        'Original_Name': '',
                                                        'Notes': ''
                                                    })
                                                    entries_in_section += 1
                                            else:
                                                self.raw_data.append({
                                                    'Month_Year_Display': month_year_display,
                                                    'Month_Year_Sortable': month_year_sortable,
                                                    'Version': version or '',
                                                    'Change_Type': change_type,
                                                    'Skill_Name': self.clean_skill_text(skill_text),
                                                    'Original_Name': '',
                                                    'Notes': ''
                                                })
                                                entries_in_section += 1
                                break
                        tabs_sibling = tabs_sibling.next_sibling

                current = current.next_sibling

            print(f"  ✓ Extracted {entries_in_section} entries")

        if not self.raw_data:
            print("❌ No data extracted from the page.")
            return False

        print(f"\n✅ Total entries extracted: {len(self.raw_data)}")
        return True

    def create_dataframe(self) -> bool:
        """
        Convert raw data to pandas DataFrame.

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.raw_data:
            print("❌ No raw data available.")
            return False

        print("\n📊 Creating DataFrame...")

        self.df = pd.DataFrame(self.raw_data)

        # Reorder columns
        column_order = [
            'Month_Year_Display',
            'Month_Year_Sortable',
            'Version',
            'Change_Type',
            'Skill_Name',
            'Original_Name',
            'Notes'
        ]

        self.df = self.df[column_order]

        # Apply date filtering if specified
        if self.date_filter:
            original_count = len(self.df)
            self.df = self.df[self.df['Month_Year_Sortable'].isin(self.date_filter)]
            filtered_count = len(self.df)
            print(f"🔍 Date filter applied: {original_count} → {filtered_count} rows")

            if filtered_count == 0:
                print("⚠️  Warning: No data matches the specified date filter!")
                print(f"   Requested: {', '.join(self.date_filter)}")
                return False

        # Apply version filtering if specified
        if self.version_filter:
            original_count = len(self.df)
            # Normalize version filter (remove 'v' prefix if present for comparison)
            normalized_versions = []
            for v in self.version_filter:
                v_clean = v.lower().replace('v', '').strip()
                normalized_versions.append(f"v{v_clean}")

            self.df = self.df[self.df['Version'].isin(normalized_versions)]
            filtered_count = len(self.df)
            print(f"🔍 Version filter applied: {original_count} → {filtered_count} rows")

            if filtered_count == 0:
                print("⚠️  Warning: No data matches the specified version filter!")
                print(f"   Requested versions: {', '.join(self.version_filter)}")
                return False

        # Sort by date (newest first)
        self.df = self.df.sort_values('Month_Year_Sortable', ascending=False)

        print(f"✅ DataFrame created with {len(self.df)} rows and {len(self.df.columns)} columns")
        print(f"\nPreview:\n{self.df.head(10)}")

        return True

    def create_summary_dataframe(self) -> pd.DataFrame:
        """
        Create a summary DataFrame showing counts by change type and month.

        Returns:
            Summary DataFrame
        """
        if self.df is None or self.df.empty:
            return pd.DataFrame()

        print("\n📈 Creating summary statistics...")

        # Summary by change type
        type_summary = self.df.groupby('Change_Type').size().reset_index(name='Count')
        type_summary = type_summary.sort_values('Count', ascending=False)

        # Summary by month
        month_summary = self.df.groupby(['Month_Year_Display', 'Month_Year_Sortable']).size().reset_index(name='Count')
        month_summary = month_summary.sort_values('Month_Year_Sortable', ascending=False)
        month_summary = month_summary[['Month_Year_Display', 'Count']]

        # Summary by month and type
        month_type_summary = self.df.groupby(['Month_Year_Display', 'Change_Type']).size().reset_index(name='Count')
        month_type_pivot = month_type_summary.pivot(index='Month_Year_Display', columns='Change_Type', values='Count')
        month_type_pivot = month_type_pivot.fillna(0).astype(int)
        month_type_pivot = month_type_pivot.reset_index()

        # Create combined summary
        summary_parts = [
            pd.DataFrame([['=== SUMMARY BY CHANGE TYPE ===']], columns=['Summary']),
            type_summary,
            pd.DataFrame([[''], ['']], columns=['Summary']),
            pd.DataFrame([['=== SUMMARY BY MONTH ===']], columns=['Summary']),
            month_summary,
            pd.DataFrame([[''], ['']], columns=['Summary']),
            pd.DataFrame([['=== DETAILED SUMMARY (MONTH × TYPE) ===']], columns=['Summary']),
            month_type_pivot,
        ]

        return type_summary, month_summary, month_type_pivot

    def export_to_excel(self, filename: str) -> bool:
        """
        Export DataFrame to Excel with formatting and summary sheet.

        Args:
            filename: Output Excel filename

        Returns:
            bool: True if successful, False otherwise
        """
        if self.df is None or self.df.empty:
            print("❌ No data to export.")
            return False

        print(f"\n💾 Exporting to Excel: {filename}")

        try:
            # Create Excel writer
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                # Write main data
                self.df.to_excel(writer, sheet_name='Changelog Data', index=False)

                # Get summary data
                type_summary, month_summary, month_type_pivot = self.create_summary_dataframe()

                # Write summary sheet
                startrow = 0

                # Type summary
                pd.DataFrame([['SUMMARY BY CHANGE TYPE']], columns=['Summary']).to_excel(
                    writer, sheet_name='Summary', startrow=startrow, index=False, header=False
                )
                startrow += 2
                type_summary.to_excel(writer, sheet_name='Summary', startrow=startrow, index=False)
                startrow += len(type_summary) + 3

                # Month summary
                pd.DataFrame([['SUMMARY BY MONTH']], columns=['Summary']).to_excel(
                    writer, sheet_name='Summary', startrow=startrow, index=False, header=False
                )
                startrow += 2
                month_summary.to_excel(writer, sheet_name='Summary', startrow=startrow, index=False)
                startrow += len(month_summary) + 3

                # Month × Type pivot
                pd.DataFrame([['DETAILED SUMMARY (MONTH × TYPE)']], columns=['Summary']).to_excel(
                    writer, sheet_name='Summary', startrow=startrow, index=False, header=False
                )
                startrow += 2
                month_type_pivot.to_excel(writer, sheet_name='Summary', startrow=startrow, index=False)

            # Format the Excel file
            self.format_excel(filename)

            print(f"✅ Successfully exported to: {filename}")
            return True

        except Exception as e:
            print(f"❌ Error exporting to Excel: {e}")
            return False

    def format_excel(self, filename: str):
        """
        Apply formatting to the Excel file.

        Args:
            filename: Excel file to format
        """
        try:
            # Load workbook
            wb = load_workbook(filename)

            # Format Changelog Data sheet
            if 'Changelog Data' in wb.sheetnames:
                ws = wb['Changelog Data']

                # Add auto-filter
                ws.auto_filter.ref = ws.dimensions

                # Format header row
                header_fill = PatternFill(start_color='366092', end_color='366092', fill_type='solid')
                header_font = Font(bold=True, color='FFFFFF')

                for cell in ws[1]:
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal='center', vertical='center')

                # Auto-size columns
                for column in ws.columns:
                    max_length = 0
                    column_letter = get_column_letter(column[0].column)

                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass

                    adjusted_width = min(max_length + 2, 50)
                    ws.column_dimensions[column_letter].width = adjusted_width

            # Format Summary sheet
            if 'Summary' in wb.sheetnames:
                ws = wb['Summary']

                # Bold headers
                for row in ws.iter_rows():
                    for cell in row:
                        if cell.value and isinstance(cell.value, str):
                            if 'SUMMARY' in cell.value.upper() or cell.value in ['Change_Type', 'Count', 'Month_Year_Display']:
                                cell.font = Font(bold=True)

                # Auto-size columns
                for column in ws.columns:
                    max_length = 0
                    column_letter = get_column_letter(column[0].column)

                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass

                    adjusted_width = min(max_length + 2, 40)
                    ws.column_dimensions[column_letter].width = adjusted_width

            # Save formatted workbook
            wb.save(filename)

        except Exception as e:
            print(f"⚠️  Warning: Could not apply formatting: {e}")

    def get_base64_excel(self, filename: str) -> Optional[str]:
        """
        Read Excel file and convert to base64 for download.

        Args:
            filename: Excel file to encode

        Returns:
            Base64 encoded string or None
        """
        try:
            with open(filename, 'rb') as f:
                excel_data = f.read()

            base64_data = base64.b64encode(excel_data).decode('utf-8')
            return f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{base64_data}"

        except Exception as e:
            print(f"❌ Error encoding file: {e}")
            return None


def get_user_date_selection() -> Tuple[Optional[List[str]], Optional[List[str]], str]:
    """
    Interactive CLI to get date range and version selection from user.

    Returns:
        Tuple of (date_filter_list, version_filter_list, description_string)
    """
    print("\n" + "=" * 80)
    print("📅 DATE RANGE SELECTION")
    print("=" * 80)
    print("\nHow would you like to filter the data?\n")
    print("1. Scrape ALL available data (no filter)")
    print("2. Scrape specific MONTH(S) (with optional version filter)")
    print("3. Scrape a DATE RANGE (from Month/Year to Month/Year, with optional version filter)")
    print()

    while True:
        choice = input("Enter your choice (1-3): ").strip()

        if choice == "1":
            print("\n✅ Selected: ALL DATA (no filtering)")
            return None, None, "Full"

        elif choice == "2":
            return get_specific_months()

        elif choice == "3":
            return get_date_range()

        else:
            print("❌ Invalid choice. Please enter 1, 2, or 3.")


def get_specific_months() -> Tuple[List[str], Optional[List[str]], str]:
    """
    Get specific months and optional version numbers from user.

    Returns:
        Tuple of (date_filter_list, version_filter_list, description_string)
    """
    print("\n" + "-" * 80)
    print("📆 SPECIFIC MONTH SELECTION")
    print("-" * 80)
    print("\nEnter month(s) you want to scrape.")
    print("Format: YYYY-MM (e.g., 2025-11 for November 2025)")
    print("You can enter multiple months separated by commas (e.g., 2025-11,2025-12)")
    print()

    while True:
        months_input = input("Enter month(s): ").strip()

        if not months_input:
            print("❌ Please enter at least one month.")
            continue

        # Split by comma and clean
        months = [m.strip() for m in months_input.split(',')]

        # Validate each month
        valid_months = []
        invalid_months = []

        for month in months:
            if validate_month_format(month):
                valid_months.append(month)
            else:
                invalid_months.append(month)

        if invalid_months:
            print(f"\n❌ Invalid month format(s): {', '.join(invalid_months)}")
            print("   Please use YYYY-MM format (e.g., 2025-11)")
            continue

        if valid_months:
            break

    # Ask for optional version filter
    version_filter = get_optional_version_filter()

    # Create description
    month_names = []
    for m in valid_months:
        year, month_num = m.split('-')
        month_name = calendar.month_name[int(month_num)]
        month_names.append(f"{month_name}_{year}")

    description = "_".join(month_names)

    if version_filter:
        version_str = "_".join([f"v{v}" for v in version_filter])
        description = f"{description}_{version_str}"

    print(f"\n✅ Selected months: {', '.join(valid_months)}")
    if version_filter:
        print(f"✅ Selected versions: {', '.join(version_filter)}")

    return valid_months, version_filter, description


def get_optional_version_filter() -> Optional[List[str]]:
    """
    Ask user if they want to filter by version numbers.

    Returns:
        List of version strings or None
    """
    print("\n" + "-" * 40)
    print("🔢 VERSION FILTER (Optional)")
    print("-" * 40)
    print("\nWould you like to also filter by specific version number(s)?")
    print("This is useful when a month has multiple versions due to website errors.")
    print()

    while True:
        choice = input("Filter by version? (y/n): ").strip().lower()

        if choice == 'n':
            return None

        elif choice == 'y':
            print("\nEnter version number(s) to include.")
            print("Format: X.XX (e.g., 9.39 for v9.39)")
            print("You can enter multiple versions separated by commas (e.g., 9.39,9.38)")
            print()

            while True:
                version_input = input("Enter version(s): ").strip()

                if not version_input:
                    print("❌ Please enter at least one version number.")
                    continue

                # Split by comma and clean
                versions = [v.strip().lower().replace('v', '') for v in version_input.split(',')]

                # Validate each version
                valid_versions = []
                invalid_versions = []

                for version in versions:
                    if validate_version_format(version):
                        valid_versions.append(version)
                    else:
                        invalid_versions.append(version)

                if invalid_versions:
                    print(f"\n❌ Invalid version format(s): {', '.join(invalid_versions)}")
                    print("   Please use X.XX format (e.g., 9.39)")
                    continue

                if valid_versions:
                    return valid_versions

        else:
            print("❌ Please enter 'y' or 'n'.")


def validate_version_format(version_str: str) -> bool:
    """
    Validate version string format (X.XX or X.X).

    Args:
        version_str: Version string to validate

    Returns:
        True if valid, False otherwise
    """
    pattern = r'^\d+\.\d+$'
    return bool(re.match(pattern, version_str))


def get_date_range() -> Tuple[List[str], Optional[List[str]], str]:
    """
    Get date range and optional version numbers from user.

    Returns:
        Tuple of (date_filter_list, version_filter_list, description_string)
    """
    print("\n" + "-" * 80)
    print("📅 DATE RANGE SELECTION")
    print("-" * 80)
    print("\nEnter the start and end months for the range.")
    print("Format: YYYY-MM (e.g., 2025-11 for November 2025)")
    print()

    while True:
        start_month = input("Enter START month (YYYY-MM): ").strip()

        if not validate_month_format(start_month):
            print("❌ Invalid format. Please use YYYY-MM (e.g., 2025-11)")
            continue

        break

    while True:
        end_month = input("Enter END month (YYYY-MM): ").strip()

        if not validate_month_format(end_month):
            print("❌ Invalid format. Please use YYYY-MM (e.g., 2025-12)")
            continue

        if end_month < start_month:
            print("❌ End month cannot be before start month.")
            continue

        break

    # Generate all months in range
    date_filter = []
    current = start_month

    while current <= end_month:
        date_filter.append(current)

        # Increment month
        year, month = map(int, current.split('-'))
        month += 1
        if month > 12:
            month = 1
            year += 1
        current = f"{year:04d}-{month:02d}"

    # Ask for optional version filter
    version_filter = get_optional_version_filter()

    # Create description
    start_year, start_month_num = start_month.split('-')
    end_year, end_month_num = end_month.split('-')

    start_name = calendar.month_name[int(start_month_num)]
    end_name = calendar.month_name[int(end_month_num)]

    if start_year == end_year:
        description = f"{start_name}_to_{end_name}_{start_year}"
    else:
        description = f"{start_name}{start_year}_to_{end_name}{end_year}"

    if version_filter:
        version_str = "_".join([f"v{v}" for v in version_filter])
        description = f"{description}_{version_str}"

    print(f"\n✅ Selected range: {start_month} to {end_month}")
    print(f"   Total months: {len(date_filter)}")
    if version_filter:
        print(f"✅ Selected versions: {', '.join(version_filter)}")

    return date_filter, version_filter, description


def validate_month_format(month_str: str) -> bool:
    """
    Validate month string format (YYYY-MM).

    Args:
        month_str: Month string to validate

    Returns:
        True if valid, False otherwise
    """
    pattern = r'^\d{4}-(0[1-9]|1[0-2])$'
    return bool(re.match(pattern, month_str))


def generate_filename(description: str) -> str:
    """
    Generate output filename with path based on date description.
    Creates outputs/reports directory if it doesn't exist.

    Args:
        description: Date description string

    Returns:
        Full filepath string
    """
    # Create outputs/reports directory if it doesn't exist
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "reports")
    os.makedirs(output_dir, exist_ok=True)

    # Get current date for the filename
    current_date = datetime.now().strftime("%Y%m%d")

    # Generate filename with date and filter description
    filename = f"Lightcast_Changelog_{current_date}_{description}.xlsx"

    return os.path.join(output_dir, filename)


def main():
    """
    Main execution function with interactive CLI.
    """
    print("=" * 80)
    print("🚀 LIGHTCAST SKILLS TAXONOMY CHANGELOG SCRAPER")
    print("=" * 80)
    print("\nWelcome! This tool scrapes the Lightcast Skills Taxonomy Changelog")
    print("and exports it to Excel with customizable date and version filtering.")

    # Get user date and version selection
    date_filter, version_filter, description = get_user_date_selection()

    # Configuration
    url = "https://docs.lightcast.dev/updates/skills-taxonomy-changelog"
    output_filename = generate_filename(description)

    print("\n" + "=" * 80)
    print("🔧 CONFIGURATION")
    print("=" * 80)
    print(f"URL: {url}")
    print(f"Output file: {os.path.basename(output_filename)}")
    print(f"Output dir: {os.path.dirname(output_filename)}")
    if date_filter:
        print(f"Date filter: {', '.join(date_filter)}")
    else:
        print("Date filter: None (scraping all data)")
    if version_filter:
        print(f"Version filter: {', '.join([f'v{v}' for v in version_filter])}")
    else:
        print("Version filter: None (all versions)")
    print()

    # Confirm before proceeding
    confirm = input("Proceed with scraping? (y/n): ").strip().lower()
    if confirm != 'y':
        print("\n❌ Scraping cancelled by user.")
        return

    # Initialize scraper
    scraper = LightcastChangelogScraper(url, date_filter, version_filter)

    # Execute scraping pipeline
    print("\n" + "=" * 80)
    print("🚀 STARTING SCRAPER")
    print("=" * 80)

    if not scraper.fetch_page():
        print("\n❌ Failed to fetch page. Exiting.")
        return

    if not scraper.scrape_all_sections():
        print("\n❌ Failed to scrape sections. Exiting.")
        return

    if not scraper.create_dataframe():
        print("\n❌ Failed to create DataFrame. Exiting.")
        return

    if not scraper.export_to_excel(output_filename):
        print("\n❌ Failed to export to Excel. Exiting.")
        return

    # Success message
    print("\n" + "=" * 80)
    print("✅ SCRAPING COMPLETE!")
    print("=" * 80)
    print(f"\n📊 Successfully exported!")
    print(f"📁 File: {os.path.basename(output_filename)}")
    print(f"📂 Location: {os.path.dirname(output_filename)}")

    if date_filter:
        print(f"📅 Filtered months: {', '.join(date_filter)}")
    else:
        print("📅 All available data included")

    if version_filter:
        print(f"🔢 Filtered versions: {', '.join([f'v{v}' for v in version_filter])}")

    print("\n" + "=" * 80)
    print("🎉 Thank you for using Lightcast Changelog Scraper!")
    print("=" * 80)


if __name__ == "__main__":
    main()
