#!/usr/bin/env python3
"""
Shared utilities for converting indexed content to Eliza-compatible markdown.
"""

import re
import json
from pathlib import Path
from datetime import datetime
import hashlib
import yaml
from typing import Dict, List, Any, Optional

def sanitize_filename(title: str, max_length: int = 100) -> str:
    """
    Convert a title to a safe filename.
    
    Args:
        title: The title to sanitize
        max_length: Maximum length of the filename
    
    Returns:
        A sanitized filename-safe string
    """
    # Remove special characters and replace with underscores
    safe_title = re.sub(r'[^\w\s-]', '', title.lower())
    safe_title = re.sub(r'[-\s]+', '_', safe_title)
    
    # Truncate if too long
    if len(safe_title) > max_length:
        safe_title = safe_title[:max_length]
    
    # Remove trailing underscores
    safe_title = safe_title.strip('_')
    
    return safe_title

def extract_domain_from_url(url: str) -> str:
    """Extract domain from URL for categorization"""
    import urllib.parse
    
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        return domain
    except:
        return 'unknown'

def categorize_by_url(url: str) -> str:
    """
    Determine knowledge category based on URL.
    
    Returns:
        Category folder name (technical, governance, ecological, community, shared)
    """
    url_lower = url.lower()
    
    # Technical content
    if any(x in url_lower for x in ['github.com', 'gitlab.com', 'docs.regen', 'guides.regen']):
        return 'technical'
    
    # Governance content
    if any(x in url_lower for x in ['governance', 'proposal', 'regen.foundation', 'vote', 'dao']):
        return 'governance'
    
    # Ecological content
    if any(x in url_lower for x in ['registry.regen', 'methodology', 'credit', 'carbon', 'biodiversity']):
        return 'ecological'
    
    # Community content
    if any(x in url_lower for x in ['forum', 'discord', 'twitter', 'medium', 'blog', 'social']):
        return 'community'
    
    # Default to shared
    return 'shared'

def categorize_by_content(content: str, title: str = "") -> str:
    """
    Determine knowledge category based on content analysis.
    """
    text_lower = (title + " " + content).lower()
    
    # Count keyword occurrences for each category
    scores = {
        'technical': 0,
        'governance': 0,
        'ecological': 0,
        'community': 0
    }
    
    # Technical keywords
    technical_keywords = ['api', 'sdk', 'code', 'function', 'class', 'method', 'implementation',
                         'algorithm', 'protocol', 'architecture', 'deployment', 'configuration']
    scores['technical'] = sum(1 for kw in technical_keywords if kw in text_lower)
    
    # Governance keywords
    governance_keywords = ['governance', 'proposal', 'voting', 'delegate', 'treasury', 'dao',
                          'stakeholder', 'decision', 'policy', 'foundation']
    scores['governance'] = sum(1 for kw in governance_keywords if kw in text_lower)
    
    # Ecological keywords
    ecological_keywords = ['carbon', 'credit', 'methodology', 'biodiversity', 'ecosystem',
                          'conservation', 'restoration', 'climate', 'nature', 'environmental']
    scores['ecological'] = sum(1 for kw in ecological_keywords if kw in text_lower)
    
    # Community keywords
    community_keywords = ['community', 'social', 'discussion', 'event', 'meetup', 'announcement',
                         'update', 'newsletter', 'podcast', 'interview']
    scores['community'] = sum(1 for kw in community_keywords if kw in text_lower)
    
    # Return category with highest score, default to shared if no clear winner
    max_score = max(scores.values())
    if max_score == 0:
        return 'shared'
    
    for category, score in scores.items():
        if score == max_score:
            return category
    
    return 'shared'

def format_frontmatter(metadata: Dict[str, Any]) -> str:
    """
    Format metadata as YAML frontmatter for markdown.
    Optimized for Eliza knowledge plugin.
    
    Args:
        metadata: Dictionary of metadata fields
    
    Returns:
        Formatted YAML frontmatter string
    """
    # Ensure required fields for Eliza
    required_fields = ['title', 'description', 'source', 'date']
    
    # Clean and validate metadata
    clean_metadata = {}
    
    # Order fields for better readability (important fields first)
    field_order = ['title', 'description', 'source', 'source_type', 'category', 
                   'subcategory', 'tags', 'date', 'url', 'author', 'version',
                   'document_id', 'koi_rid']
    
    # Add ordered fields first
    for field in field_order:
        if field in metadata and metadata[field] is not None:
            value = metadata[field]
            # Convert lists to proper YAML format
            if isinstance(value, list):
                clean_metadata[field] = value
            # Keep strings, numbers, booleans
            elif isinstance(value, (str, int, float, bool)):
                clean_metadata[field] = value
            # Convert datetime objects to ISO strings
            elif hasattr(value, 'isoformat'):
                clean_metadata[field] = value.isoformat()
            else:
                clean_metadata[field] = str(value)
    
    # Add remaining fields
    for key, value in metadata.items():
        if key not in field_order and value is not None:
            if isinstance(value, list):
                clean_metadata[key] = value
            elif isinstance(value, (str, int, float, bool)):
                clean_metadata[key] = value
            elif hasattr(value, 'isoformat'):
                clean_metadata[key] = value.isoformat()
            else:
                clean_metadata[key] = str(value)
    
    # Ensure critical fields exist
    if 'date' not in clean_metadata:
        clean_metadata['date'] = datetime.now().strftime('%Y-%m-%d')
    
    if 'description' not in clean_metadata:
        clean_metadata['description'] = f"Documentation for {clean_metadata.get('title', 'Regen Network')}"
    
    # Format as YAML with proper indentation for lists
    try:
        # Custom formatting for better readability
        lines = ["---"]
        for key, value in clean_metadata.items():
            if isinstance(value, list):
                if len(value) == 0:
                    lines.append(f"{key}: []")
                elif len(value) == 1:
                    lines.append(f"{key}: [{value[0]}]")
                else:
                    lines.append(f"{key}:")
                    for item in value:
                        lines.append(f"  - {item}")
            elif isinstance(value, str) and ('\n' in value or len(value) > 80):
                # Multi-line strings
                lines.append(f"{key}: |")
                for line in value.split('\n'):
                    lines.append(f"  {line}")
            else:
                # Simple values
                if isinstance(value, str) and ':' in value:
                    lines.append(f'{key}: "{value}"')
                else:
                    lines.append(f"{key}: {value}")
        lines.append("---\n")
        return "\n".join(lines)
    except Exception as e:
        # Fallback to yaml.dump if custom formatting fails
        frontmatter = yaml.dump(clean_metadata, default_flow_style=False, allow_unicode=True)
        return f"---\n{frontmatter}---\n\n"

def preserve_code_blocks(content: str) -> str:
    """
    Ensure code blocks are properly formatted in markdown.
    """
    # Already has code blocks, ensure they're properly formatted
    if '```' in content:
        return content
    
    # Look for code-like patterns and wrap them
    lines = content.split('\n')
    result = []
    in_code = False
    code_buffer = []
    
    for line in lines:
        # Detect code patterns (indented lines, function definitions, etc.)
        is_code = (
            line.startswith('    ') or  # Indented
            line.startswith('\t') or    # Tab indented
            re.match(r'^(def |class |function |const |var |let )', line) or  # Code keywords
            re.match(r'^\s*[{}()\[\];]$', line)  # Just brackets
        )
        
        if is_code and not in_code:
            in_code = True
            code_buffer = [line]
        elif is_code and in_code:
            code_buffer.append(line)
        elif not is_code and in_code:
            # End of code block
            result.append('```')
            result.extend(code_buffer)
            result.append('```')
            result.append(line)
            in_code = False
            code_buffer = []
        else:
            result.append(line)
    
    # Handle remaining code buffer
    if in_code and code_buffer:
        result.append('```')
        result.extend(code_buffer)
        result.append('```')
    
    return '\n'.join(result)

def split_large_content(content: str, max_size: int = 100000) -> List[str]:
    """
    Split large content into multiple parts if necessary.
    
    Args:
        content: The content to potentially split
        max_size: Maximum size in characters (default 100KB)
    
    Returns:
        List of content parts
    """
    if len(content) <= max_size:
        return [content]
    
    # Try to split at natural boundaries
    parts = []
    current_part = []
    current_size = 0
    
    # First try to split by major sections (## headers)
    sections = re.split(r'\n(?=## )', content)
    
    for section in sections:
        section_size = len(section)
        
        if current_size + section_size > max_size and current_part:
            # Save current part and start new one
            parts.append('\n'.join(current_part))
            current_part = [section]
            current_size = section_size
        else:
            current_part.append(section)
            current_size += section_size
    
    # Add remaining part
    if current_part:
        parts.append('\n'.join(current_part))
    
    return parts

def generate_content_id(content: str, source: str) -> str:
    """
    Generate a unique content ID based on content hash.
    """
    # Create hash from content + source
    hash_input = f"{source}:{content[:1000]}"  # Use first 1000 chars
    content_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:12]
    return content_hash

def clean_html_content(content: str) -> str:
    """
    Clean HTML artifacts from content.
    """
    # Remove HTML tags
    content = re.sub(r'<[^>]+>', '', content)
    
    # Decode HTML entities
    import html
    content = html.unescape(content)
    
    # Remove excessive whitespace
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
    
    return content.strip()

def generate_description(content: str, title: str = "", max_length: int = 200) -> str:
    """
    Generate a 1-2 sentence description from document content.
    Optimized for Eliza's search functionality.
    """
    # Clean content for processing
    text = clean_html_content(content)
    
    # Remove code blocks for description
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    
    # Try to find a good introductory paragraph
    paragraphs = text.split('\n\n')
    
    # Look for overview, introduction, or summary sections
    for i, para in enumerate(paragraphs[:10]):  # Check first 10 paragraphs
        para_lower = para.lower()
        if any(keyword in para_lower for keyword in ['overview', 'introduction', 'summary', 'this document', 'this guide', 'this tutorial']):
            # Use the next paragraph if this is just a heading
            if len(para) < 50 and i + 1 < len(paragraphs):
                description = paragraphs[i + 1]
            else:
                description = para
            break
    else:
        # Use first substantial paragraph if no intro found
        for para in paragraphs:
            if len(para) > 50:
                description = para
                break
        else:
            description = text[:500]  # Fallback to first 500 chars
    
    # Clean and truncate
    description = re.sub(r'\s+', ' ', description).strip()
    
    # Remove markdown formatting
    description = re.sub(r'[#*_\[\]()]', '', description)
    
    # Smart truncation at sentence boundary
    if len(description) > max_length:
        # Try to cut at sentence end
        sentences = re.split(r'(?<=[.!?])\s+', description)
        result = ""
        for sentence in sentences:
            if len(result) + len(sentence) <= max_length:
                result += sentence + " "
            elif not result:
                # If first sentence is too long, truncate it
                result = sentence[:max_length-3] + "..."
                break
            else:
                break
        description = result.strip()
    
    # Add title context if description is too generic
    if description and len(description) < 50:
        description = f"{title}: {description}"
    elif not description:
        description = f"Documentation about {title}"
    
    return description

def extract_tags_from_content(content: str, title: str = "") -> List[str]:
    """
    Extract relevant tags from content for categorization.
    Enhanced for Eliza with more specific, actionable tags.
    """
    text = (title + " " + content).lower()
    tags = []
    
    # Technical specific tags
    technical_patterns = {
        'cosmos-sdk': r'\bcosmos[\s-]?sdk\b',
        'tendermint': r'\btendermint\b',
        'ibc-protocol': r'\bibc\b|\binter[\s-]?blockchain',
        'x-ecocredit': r'\bx[\s/]ecocredit\b',
        'x-data': r'\bx[\s/]data\b',
        'x-intertx': r'\bx[\s/]intertx\b',
        'protobuf': r'\bprotobuf\b|\bproto\b',
        'grpc': r'\bgrpc\b',
        'rest-api': r'\brest[\s-]?api\b',
        'cli-commands': r'\bcli\b|\bcommand[\s-]?line',
        'smart-contracts': r'\bsmart[\s-]?contract',
        'wasm': r'\bwasm\b|\bcosmwasm\b',
        'upgrade-handler': r'\bupgrade[\s-]?handler',
        'migration-guide': r'\bmigration\b',
        'validator-setup': r'\bvalidator\b',
        'node-operation': r'\bnode\b.*\boperat',
    }
    
    # Governance specific tags
    governance_patterns = {
        'proposal-draft': r'\bproposal\b.*\bdraft',
        'parameter-change': r'\bparameter[\s-]?change',
        'software-upgrade': r'\bsoftware[\s-]?upgrade',
        'community-spend': r'\bcommunity[\s-]?spend',
        'voting-guide': r'\bvoting\b|\bvote\b',
        'delegation': r'\bdelega',
        'staking': r'\bstak',
        'treasury': r'\btreasury\b',
        'foundation-updates': r'\bfoundation\b.*\bupdate',
    }
    
    # Ecological specific tags
    ecological_patterns = {
        'carbon-credits': r'\bcarbon[\s-]?credit',
        'biodiversity-credits': r'\bbiodiversity[\s-]?credit',
        'methodology-vm0042': r'\bvm0042\b',
        'methodology-vm0022': r'\bvm0022\b',
        'verra-vcs': r'\bverra\b|\bvcs\b',
        'gold-standard': r'\bgold[\s-]?standard\b',
        'nature-based': r'\bnature[\s-]?based',
        'soil-carbon': r'\bsoil[\s-]?carbon',
        'forest-conservation': r'\bforest\b.*\bconservation',
        'regenerative-agriculture': r'\bregenerat.*\bagricult',
        'carbon-sequestration': r'\bcarbon[\s-]?sequest',
        'additionality': r'\badditional',
        'permanence': r'\bpermanen',
        'mrv-system': r'\bmrv\b|\bmonitor.*report.*verif',
    }
    
    # Implementation specific tags
    implementation_patterns = {
        'typescript': r'\btypescript\b',
        'golang': r'\bgolang\b|\bgo\b(?:lang)?',
        'rust': r'\brust\b',
        'python': r'\bpython\b',
        'react': r'\breact\b',
        'nextjs': r'\bnext\.?js\b',
        'graphql': r'\bgraphql\b',
        'postgresql': r'\bpostgres',
        'docker': r'\bdocker\b',
        'kubernetes': r'\bkubernetes\b|\bk8s\b',
        'github-actions': r'\bgithub[\s-]?action',
        'ci-cd': r'\bci\/cd\b|\bcontinuous[\s-]?integrat',
    }
    
    # Check all pattern groups
    all_patterns = {
        **technical_patterns,
        **governance_patterns,
        **ecological_patterns,
        **implementation_patterns
    }
    
    for tag, pattern in all_patterns.items():
        if re.search(pattern, text):
            tags.append(tag)
    
    # Add general topic tags if specific ones weren't found
    if len(tags) < 3:
        general_patterns = {
            'blockchain': r'\bblockchain\b',
            'defi': r'\bdefi\b|\bdecentralized[\s-]?finance',
            'web3': r'\bweb3\b',
            'dao': r'\bdao\b|\bdecentralized.*organization',
            'regenerative': r'\bregenerat',
            'sustainability': r'\bsustainab',
            'climate-action': r'\bclimate\b',
            'ecosystem-services': r'\becosystem[\s-]?service',
        }
        
        for tag, pattern in general_patterns.items():
            if re.search(pattern, text) and tag not in tags:
                tags.append(tag)
    
    return list(set(tags))[:15]  # Remove duplicates, limit to 15 tags

def create_markdown_document(
    title: str,
    content: str,
    metadata: Dict[str, Any],
    source_url: Optional[str] = None
) -> str:
    """
    Create a complete markdown document with frontmatter and content.
    
    Args:
        title: Document title
        content: Main content
        metadata: Metadata for frontmatter
        source_url: Optional source URL for attribution
    
    Returns:
        Complete markdown document as string
    """
    # Ensure title in metadata
    if 'title' not in metadata:
        metadata['title'] = title
    
    # Format frontmatter
    frontmatter = format_frontmatter(metadata)
    
    # Clean and format content
    content = clean_html_content(content)
    content = preserve_code_blocks(content)
    
    # Build document
    document = frontmatter
    document += f"# {title}\n\n"
    document += content
    
    # Add source attribution if provided
    if source_url:
        document += f"\n\n---\n*Source: [{source_url}]({source_url})*\n"
        document += f"*Indexed: {datetime.now().strftime('%Y-%m-%d')}*\n"
    
    return document

def save_markdown_file(
    content: str,
    filename: str,
    output_dir: Path,
    overwrite: bool = False
) -> Path:
    """
    Save markdown content to file.
    
    Args:
        content: Markdown content to save
        filename: Name of the file (without .md extension)
        output_dir: Directory to save in
        overwrite: Whether to overwrite existing files
    
    Returns:
        Path to saved file
    """
    # Ensure output directory exists
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Add .md extension if not present
    if not filename.endswith('.md'):
        filename += '.md'
    
    # Full path
    file_path = output_dir / filename
    
    # Check if file exists
    if file_path.exists() and not overwrite:
        # Add timestamp to make unique
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = filename.replace('.md', f'_{timestamp}.md')
        file_path = output_dir / filename
    
    # Save file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return file_path

def load_json_document(file_path: Path) -> Dict[str, Any]:
    """
    Load and validate a JSON document.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return {}

def batch_process_files(
    file_pattern: str,
    source_dir: Path,
    process_func,
    max_files: Optional[int] = None
) -> List[Path]:
    """
    Batch process files matching a pattern.
    
    Args:
        file_pattern: Glob pattern for files
        source_dir: Directory to search in
        process_func: Function to process each file
        max_files: Optional limit on number of files
    
    Returns:
        List of processed file paths
    """
    source_dir = Path(source_dir)
    files = list(source_dir.glob(file_pattern))
    
    if max_files:
        files = files[:max_files]
    
    processed = []
    for i, file_path in enumerate(files, 1):
        try:
            result = process_func(file_path)
            processed.append(result)
            if i % 10 == 0:
                print(f"Processed {i}/{len(files)} files...")
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
    
    return processed

# Test function
def test_utils():
    """Test utility functions"""
    print("Testing conversion utilities...")
    
    # Test filename sanitization
    assert sanitize_filename("Hello World! @#$%") == "hello_world"
    assert sanitize_filename("Very Long Title " * 20)[:100] == sanitize_filename("Very Long Title " * 20)
    
    # Test categorization
    assert categorize_by_url("https://github.com/regen-network/regen-ledger") == "technical"
    assert categorize_by_url("https://regen.foundation/governance") == "governance"
    assert categorize_by_url("https://registry.regen.network") == "ecological"
    
    # Test frontmatter
    metadata = {
        "source": "github",
        "title": "Test Doc",
        "tags": ["test", "example"],
        "date": "2024-01-01"
    }
    fm = format_frontmatter(metadata)
    assert "---" in fm
    assert "source: github" in fm
    
    print("All tests passed!")

if __name__ == "__main__":
    test_utils()