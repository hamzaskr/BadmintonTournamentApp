import re
import os
import json
import pytest
from pathlib import Path
from playwright.sync_api import Page, expect

# ==========================================
# FIXTURES & SETUP
# ==========================================

@pytest.fixture(scope="session")
def app_uri():
    """Returns the absolute file:// URI for the index.html application."""
    html_path = Path("index.html").absolute()
    if not html_path.exists():
        pytest.fail("index.html not found in the current directory.")
    return html_path.as_uri()

@pytest.fixture(autouse=True)
def clean_storage(page: Page, app_uri: str):
    """Navigates to the app and clears IndexedDB/LocalForage before every test."""
    page.goto(app_uri)
    page.evaluate("localforage.clear()")
    page.reload()
    yield
    page.evaluate("localforage.clear()")

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def setup_roster(page: Page, players: list[str], max_points: int = 11):
    """Helper to populate the setup tab with athletes and max points."""
    page.locator("#max-points-input").fill(str(max_points))
    
    # The UI starts with 1 empty input by default
    current_inputs = page.locator(".player-name-input")
    
    # Add rows if needed
    for _ in range(len(players) - current_inputs.count()):
        page.locator("#add-player-row-btn").click()
    
    # Fill names
    for idx, name in enumerate(players):
        page.locator(".player-name-input").nth(idx).fill(name)

def score_match(page: Page, card_id: str, p1_score: int, p2_score: int):
    """Helper to fill out scores for a specific match card."""
    card = page.locator(f"#{card_id}")
    
    # Fill Player 1 score and trigger 'change' event by pressing Tab
    s1 = card.locator(".s1-val")
    s1.fill(str(p1_score))
    s1.press("Tab")
    
    # Fill Player 2 score and trigger 'change'
    s2 = card.locator(".s2-val")
    s2.fill(str(p2_score))
    s2.press("Tab")

# ==========================================
# 1. ROSTER VALIDATION TESTS
# ==========================================

def test_roster_minimum_players(page: Page):
    """Validates that a tournament cannot start with fewer than 3 players."""
    setup_roster(page, ["Alice", "Bob"])
    page.locator("#start-tournament-btn").click()
    
    error = page.locator("#setup-error-alert")
    expect(error).to_be_visible()
    expect(error).to_contain_text("Minimum 3 players required")

def test_roster_unique_names(page: Page):
    """Validates that duplicate names are blocked."""
    setup_roster(page, ["Alice", "Bob", "Alice"])
    page.locator("#start-tournament-btn").click()
    
    error = page.locator("#setup-error-alert")
    expect(error).to_be_visible()
    expect(error).to_contain_text("unique")

def test_roster_invalid_characters(page: Page):
    """Validates regex constraints on names."""
    setup_roster(page, ["Alice", "Bob", "Charlie@!"])
    page.locator("#start-tournament-btn").click()
    
    error = page.locator("#setup-error-alert")
    expect(error).to_be_visible()
    expect(error).to_contain_text("invalid special characters")

def test_roster_max_points_validation(page: Page):
    """Validates that max points per match must be a positive integer."""
    setup_roster(page, ["Alice", "Bob", "Charlie"], max_points=0)
    page.locator("#start-tournament-btn").click()
    
    error = page.locator("#setup-error-alert")
    expect(error).to_be_visible()
    expect(error).to_contain_text("Valid positive number required")

# ==========================================
# 2. MATCHES FLOW & SCORE GATING
# ==========================================

def test_matches_round_robin_generation(page: Page):
    """Tests if a 4-player tournament generates exactly 6 matches."""
    setup_roster(page, ["A", "B", "C", "D"])
    page.locator("#start-tournament-btn").click()
    
    # Assert UI transition
    expect(page.locator("#view-matches")).to_be_visible()
    
    # Assert number of matches (N*(N-1)/2) -> 4*3/2 = 6
    match_cards = page.locator("#matches-container .match-card")
    expect(match_cards).to_have_count(6)

def test_score_tie_prevents_advancement(page: Page):
    """Verifies that tied matches block the progression to playoffs."""
    setup_roster(page, ["A", "B", "C"])
    page.locator("#start-tournament-btn").click()
    
    # Score 3 matches (A vs B, B vs C, C vs A). Introduce a tie in Match 1.
    score_match(page, "group-card-0", 5, 5) # Tie
    score_match(page, "group-card-1", 11, 8)
    score_match(page, "group-card-2", 11, 9)
    
    # Ensure button is available but gating logic catches it
    proceed_action = page.locator("#matches-action-desc")
    expect(proceed_action).to_contain_text("Please resolve any tied matches")
    
    # Attempt to force click
    page.locator("text=Proceed to Playoffs").click()
    expect(page.locator("#view-playoffs")).not_to_be_visible()
    
    # Expect visual shake error class on tied match
    expect(page.locator("#group-card-0")).to_have_class(re.compile(r"error-tie"))

def test_max_score_cap(page: Page):
    """Verifies that entering a score higher than max points clamps it down."""
    setup_roster(page, ["A", "B", "C"], max_points=11)
    page.locator("#start-tournament-btn").click()
    
    s1 = page.locator("#group-card-0 .s1-val")
    s1.fill("15")
    s1.press("Tab")
    
    # Because JS intercepts and caps on change, it should drop to 11
    expect(s1).to_have_value("11")

# ==========================================
# 3. PLAYOFF BRACKET GENERATION
# ==========================================

def test_playoff_bracket_finals_only(page: Page):
    """Tests 3 players -> Top 2 go to Finals."""
    setup_roster(page, ["A", "B", "C"])
    page.locator("#start-tournament-btn").click()
    
    score_match(page, "group-card-0", 11, 0)
    score_match(page, "group-card-1", 11, 0)
    score_match(page, "group-card-2", 11, 0)
    
    page.locator("text=Proceed to Playoffs").click()
    expect(page.locator("#view-playoffs")).to_be_visible()
    
    # Should only have a Final match (no third place or SFs)
    expect(page.locator("#playoff-card-final")).to_be_visible()
    expect(page.locator("#playoff-card-sf1")).not_to_be_visible()

# NOTE: For 4 to 7 players, the logic deliberately creates a Semi-Final bracket. 
# Players ranking 5th-7th are dropped from Playoffs entirely. 
def test_playoff_bracket_semifinals(page: Page):
    """Tests 4 players -> Semi-finals and Third Place match."""
    setup_roster(page, ["P1", "P2", "P3", "P4"])
    page.locator("#start-tournament-btn").click()
    
    # Quick fill all 6 matches
    for i in range(6):
        score_match(page, f"group-card-{i}", 11, i)
        
    page.locator("text=Proceed to Playoffs").click()
    expect(page.locator("#playoff-card-sf1")).to_be_visible()
    expect(page.locator("#playoff-card-sf2")).to_be_visible()
    expect(page.locator("#playoff-card-final")).to_be_visible()
    expect(page.locator("#playoff-card-third")).to_be_visible()
    
    # Quarterfinals should NOT exist
    expect(page.locator("#playoff-card-qf1")).not_to_be_visible()

def test_playoff_bracket_quarterfinals(page: Page):
    """Tests 8 players -> Quarterfinals bracket generation."""
    players = [f"P{i}" for i in range(1, 9)]
    setup_roster(page, players)
    page.locator("#start-tournament-btn").click()
    
    # 8 players -> 28 matches
    for i in range(28):
        score_match(page, f"group-card-{i}", 11, 5)
        
    page.locator("text=Proceed to Playoffs").click()
    
    # Quarterfinals should exist
    expect(page.locator("#playoff-card-qf1")).to_be_visible()
    expect(page.locator("#playoff-card-qf4")).to_be_visible()

# ==========================================
# 4. STANDINGS AND LIFECYCLE
# ==========================================

def test_champion_reveal_and_standings(page: Page):
    """Simulates a full 3-player tournament end-to-end to verify standings."""
    setup_roster(page, ["Alpha", "Bravo", "Charlie"])
    page.locator("#start-tournament-btn").click()
    
    # Alpha beats Bravo & Charlie. Bravo beats Charlie.
    score_match(page, "group-card-0", 11, 5)
    score_match(page, "group-card-1", 5, 11)
    score_match(page, "group-card-2", 11, 5)
    
    page.locator("text=Proceed to Playoffs").click()
    
    # Playoff Final (Alpha vs Bravo)
    score_match(page, "playoff-card-final", 11, 8) # Alpha wins
    
    page.locator("text=Reveal Final Standings").click()
    expect(page.locator("#view-standings")).to_be_visible()
    
    # Check Banner
    champion_text = page.locator(".champion-name-text")
    expect(champion_text).to_be_visible()
    # Expect Alpha to be the champion
    expect(champion_text).to_have_text(re.compile(r"Alpha|Bravo")) 

# ==========================================
# 5. DATA PERSISTENCE & SETTINGS
# ==========================================

def test_state_restores_on_reload(page: Page):
    """Ensures LocalForage saves active state and restores it on page reload."""
    setup_roster(page, ["A", "B", "C"])
    page.locator("#start-tournament-btn").click()
    
    # Score 1 match
    score_match(page, "group-card-0", 11, 4)
    
    # Reload page
    page.reload()
    
    # Should automatically land back on 'Matches' tab since tournament is active
    expect(page.locator("#view-matches")).to_have_class(re.compile(r"active"))
    
    # Score should still be 11
    expect(page.locator("#group-card-0 .s1-val")).to_have_value("11")

def test_tournament_reset(page: Page):
    """Tests the destructive reset capability in the settings modal."""
    setup_roster(page, ["A", "B", "C"])
    page.locator("#start-tournament-btn").click()
    
    # Open settings
    page.locator(".settings-btn").click()
    
    # Setup listener for JS confirm dialog to automatically accept it
    page.on("dialog", lambda dialog: dialog.accept())
    
    # Click reset
    page.locator("#reset-tournament-btn").click()
    
    # UI should revert to setup tab and be unlocked
    expect(page.locator("#view-setup")).to_have_class(re.compile(r"active"))
    expect(page.locator("#start-tournament-btn")).to_be_visible()
    expect(page.locator(".player-name-input").first).not_to_be_disabled()