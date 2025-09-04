"""
Known entities for Regen Network knowledge graph
Curated lists of verified people and organizations
"""

# Known people in the Regen Network ecosystem
KNOWN_PEOPLE = [
    # Core team and founders
    "Gregory Landua",
    "Will Szal",
    "Sam Vitello",
    "Aaron Craelius",
    
    # Team members from website
    "Becca Harman",
    "Tica Lubin",
    "Gisel Booman",
    "Ned Horning",
    
    # External notable people
    "Maya Angelou",  # Quote attribution
    "Austin Federa",  # Solana Foundation
    "Martin Wainstein",  # Open Earth Foundation
    "Charlie Baker",
    "Sari Lott",
    "Sonny Hallett",
    
    # Podcast guests and speakers
    "Cyrus of Eden",
]

# Known organizations
KNOWN_ORGANIZATIONS = [
    # Core Regen entities
    "Regen Network",
    "Regen Foundation", 
    "Regen Ledger",
    "Regen Registry",
    "Regen Network Development",
    "Regen Network Development PBC",
    "RND PBC",
    "Regen Marketplace",
    
    # Partner organizations
    "GitHub",
    "Discord",
    "Cosmos",
    "Cosmos SDK",
    "ZenHub",
    
    # Standards bodies and registries
    "Verra",
    "Gold Standard",
    "Climate Action Reserve",
    
    # Blockchain and tech partners
    "Solana Foundation",
    "The Solana Foundation",
    "Solana Network",
    "Open Earth Foundation",
    "Planet Labs",
    "Digital Globe",
    
    # Other partners
    "Terrasos",
    "Eden DAO",
    "Community Staking DAO",
    "ecoToken",
    "Fundacion Pachamama",
    "Pachamama Alliance",
    "Amazon Sacred Headwaters Alliance",
    "NaturaTech LAC",
    "Stoknes Futures",
]

# Terms that are definitely NOT people (commonly misextracted)
NOT_PEOPLE = [
    # Technical terms
    "Regen Mainnet",
    "Regen Testnet", 
    "Redwood Testnet",
    "Local Testnet",
    "Cosmos SDK",
    "Regen App",
    
    # Actions/commands
    "Install Regen",
    "Update Go",
    "Manage Keys",
    "Create Validator",
    "Initialize Node",
    "Using Cosmovisor",
    "Without Cosmovisor",
    "Using Quickstart",
    "Using State Sync",
    
    # Documentation sections
    "Release Notes",
    "Release Process",
    "Upgrade Guide",
    "Upgrade Overview", 
    "Upgrade Info",
    "Upgrade Height",
    "Migration Guide",
    "Migration Overview",
    "Change Log",
    "Contributor Covenant",
    "Code of Conduct",
    "Security Policy",
    
    # UI elements
    "Discord Server",
    "Submitting Issues",
    "Reviewing Proposals",
    "Writing Documentation",
    "Writing Specifications",
    "Additional Documentation",
    "For Bugs",
    "For Features",
    "Getting Started",
    "Requesting Reviews",
    "Individual Commits",
    "Author Checklist",
    
    # Generic terms
    "Our Pledge",
    "Our Standards",
    "Our Responsibilities",
    "Legal Entity",
    "Derivative Works",
    "If You",
    "Example Output",
    "Quick Start",
    "Line Interface",
    "Initial Setup",
    "Blockchain Basics",
    "Wallet Security",
    "Credit Class",
    "Credit Type",
    "Go Downloads",
    
    # Navigation/structural elements
    "Learn More",
    "Read More",
    "View More",
    "See More",
    "Click Here",
    "Previous Page",
    "Next Page",
    "Table of Contents",
    "Prerequisites",
    "Requirements",
    "Introduction",
    "Conclusion",
    "Summary",
    "Overview",
]

# Terms that are definitely NOT organizations (commonly misextracted)
NOT_ORGANIZATIONS = [
    # Generic terms
    "The network",
    "A network",
    "The foundation",
    "A foundation",
    "The registry",
    "The platform",
    "The marketplace",
    "The ledger",
    "The app",
    
    # Partial sentences
    "Before these DAO",
    "For Regen Network",
    "For the Regen Network",
    "About Regen Network",
    "Written by Regen Network",
    "Published in Regen Network",
    "Welcome to Regen Network",
    "While Regen Network",
    "Although Regen Network",
    "Access the Regen Network",
    "Connect to Regen Network",
    
    # Other fragments
    "This foundation",
    "This technological foundation",
    "While the foundation",
    "Soil is the foundation",
    "Legal reflection of DAO",
    "Goal and Foundation",
    "Stake blockchain network",
    "Bioregional sensor network",
]


def is_known_person(name: str) -> bool:
    """Check if a name is a known person"""
    return name in KNOWN_PEOPLE


def is_known_organization(name: str) -> bool:
    """Check if a name is a known organization"""
    return name in KNOWN_ORGANIZATIONS


def is_definitely_not_person(name: str) -> bool:
    """Check if a term is definitely not a person"""
    return name in NOT_PEOPLE or name.lower() in [p.lower() for p in NOT_PEOPLE]


def is_definitely_not_organization(name: str) -> bool:
    """Check if a term is definitely not an organization"""
    return name in NOT_ORGANIZATIONS or name.lower() in [o.lower() for o in NOT_ORGANIZATIONS]


def normalize_organization_name(name: str) -> str:
    """Normalize organization names to handle variations"""
    # Handle common variations
    variations = {
        "Regen Network Development PBC": "Regen Network Development",
        "RND PBC": "Regen Network Development",
        "The Solana Foundation": "Solana Foundation",
        "Cosmos SDK": "Cosmos",
    }
    
    return variations.get(name, name)