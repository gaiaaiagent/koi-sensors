"""
Style Enforcer - Applies style guide rules to thread posts
Based on David Fortson / Many Mangos style guidelines
"""

import re
from typing import Dict, Any, List, Tuple, Optional
from loguru import logger


class StyleEnforcer:
    """
    Enforces style guide compliance for Twitter threads
    Implements Milestone B requirement: style guide from David Fortson / Many Mangos
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize with configuration"""
        self.config = config.get('x_bot', {})
        self.style_config = self.config.get('style_guide', {})
        self.validation_config = self.config.get('validation', {})
        
        # Style parameters
        self.tone = self.style_config.get('tone', 'professional_friendly')
        self.no_speculation = self.validation_config.get('no_speculation', True)
        self.require_sources = self.validation_config.get('require_sources', True)
        
        # Forbidden phrases (speculation)
        self.speculation_phrases = [
            'might be', 'could be', 'possibly', 'potentially',
            'may lead to', 'expected to', 'likely to', 'probable',
            'rumors', 'unconfirmed', 'allegedly', 'supposedly',
            'we believe', 'we think', 'we expect', 'we predict'
        ]
        
        # Required professional tone markers
        self.professional_markers = [
            'announced', 'confirmed', 'launched', 'released',
            'published', 'verified', 'documented', 'recorded',
            'achieved', 'completed', 'established', 'implemented'
        ]
        
        # Style guide rules
        self.rules = {
            'no_all_caps': True,
            'no_excessive_punctuation': True,
            'professional_language': True,
            'clear_cta': True,
            'consistent_voice': True,
            'factual_only': True
        }
    
    def enforce_style(self, thread: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply style guide enforcement to a thread
        
        Args:
            thread: Thread data with posts
            
        Returns:
            Thread with style enforcement applied and scoring
        """
        enforced_posts = []
        total_score = 0
        issues = []
        
        for post in thread.get('posts', []):
            enforced_post, score, post_issues = self._enforce_post_style(post)
            enforced_posts.append(enforced_post)
            total_score += score
            issues.extend(post_issues)
        
        # Calculate average style score
        avg_score = total_score / len(enforced_posts) if enforced_posts else 0
        
        # Update thread with enforced posts
        thread['posts'] = enforced_posts
        thread['style_score'] = avg_score
        thread['style_issues'] = issues
        thread['style_compliant'] = avg_score >= 0.8  # 80% threshold
        
        logger.info(f"Style enforcement complete. Score: {avg_score:.2f}, Issues: {len(issues)}")
        
        return thread
    
    def _enforce_post_style(self, post: Dict[str, Any]) -> Tuple[Dict[str, Any], float, List[str]]:
        """
        Enforce style on a single post
        
        Args:
            post: Post data
            
        Returns:
            Tuple of (enforced post, score, issues)
        """
        content = post.get('content', '')
        issues = []
        score = 1.0  # Start with perfect score
        
        # Apply each rule
        if self.rules['no_all_caps']:
            content, caps_issue = self._fix_all_caps(content)
            if caps_issue:
                issues.append(caps_issue)
                score -= 0.1
        
        if self.rules['no_excessive_punctuation']:
            content, punct_issue = self._fix_excessive_punctuation(content)
            if punct_issue:
                issues.append(punct_issue)
                score -= 0.1
        
        if self.no_speculation:
            content, spec_issues = self._remove_speculation(content)
            if spec_issues:
                issues.extend(spec_issues)
                score -= 0.2 * len(spec_issues)
        
        if self.rules['professional_language']:
            professional_score = self._check_professional_tone(content)
            if professional_score < 0.5:
                issues.append("Low professional tone score")
                score -= 0.2
        
        if self.rules['clear_cta'] and post.get('type') == 'cta':
            if not self._has_clear_cta(content):
                content = self._improve_cta(content)
                issues.append("CTA improved for clarity")
                score -= 0.1
        
        # Ensure score doesn't go below 0
        score = max(0, score)
        
        # Update post
        post['content'] = content
        post['char_count'] = len(content)
        post['style_score'] = score
        
        return post, score, issues
    
    def _fix_all_caps(self, content: str) -> Tuple[str, Optional[str]]:
        """Fix excessive use of capital letters"""
        # Check if more than 30% of alphabetic characters are uppercase
        alpha_chars = [c for c in content if c.isalpha()]
        if not alpha_chars:
            return content, None
        
        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        
        if upper_ratio > 0.3 and len(alpha_chars) > 10:
            # Find all-caps words (3+ characters)
            words = content.split()
            fixed_words = []
            for word in words:
                # Keep acronyms and short words
                if len(word) > 3 and word.isupper() and not word.startswith('#'):
                    fixed_words.append(word.capitalize())
                else:
                    fixed_words.append(word)
            
            fixed_content = ' '.join(fixed_words)
            if fixed_content != content:
                return fixed_content, "Fixed excessive capitals"
        
        return content, None
    
    def _fix_excessive_punctuation(self, content: str) -> Tuple[str, Optional[str]]:
        """Fix excessive punctuation marks"""
        issue = None
        
        # Replace multiple exclamation marks
        if '!!!' in content:
            content = re.sub(r'!{3,}', '!', content)
            issue = "Reduced excessive exclamation marks"
        
        # Replace multiple question marks
        if '???' in content:
            content = re.sub(r'\?{3,}', '?', content)
            issue = "Reduced excessive question marks"
        
        # Replace excessive dots
        if re.search(r'\.{4,}', content):
            content = re.sub(r'\.{4,}', '...', content)
            if not issue:
                issue = "Fixed excessive dots"
        
        return content, issue
    
    def _remove_speculation(self, content: str) -> Tuple[str, List[str]]:
        """Remove speculative language"""
        issues = []
        content_lower = content.lower()
        
        for phrase in self.speculation_phrases:
            if phrase in content_lower:
                # Try to rephrase or remove speculative language
                # This is a simple approach - could be more sophisticated
                if phrase in ['might be', 'could be']:
                    content = re.sub(
                        rf'\b(might|could)\s+be\b',
                        'is',
                        content,
                        flags=re.IGNORECASE
                    )
                    issues.append(f"Removed speculation: '{phrase}'")
                elif phrase in ['possibly', 'potentially']:
                    content = re.sub(
                        rf'\b{phrase}\b',
                        '',
                        content,
                        flags=re.IGNORECASE
                    )
                    content = ' '.join(content.split())  # Clean up extra spaces
                    issues.append(f"Removed speculation: '{phrase}'")
        
        return content, issues
    
    def _check_professional_tone(self, content: str) -> float:
        """Check if content has professional tone"""
        content_lower = content.lower()
        
        # Count professional markers
        marker_count = sum(1 for marker in self.professional_markers 
                          if marker in content_lower)
        
        # Check for informal language
        informal_patterns = [
            r'\b(lol|omg|wtf|tbh|imo|imho)\b',
            r'\b(gonna|wanna|gotta|kinda|sorta)\b',
            r'\b(awesome|amazing|incredible|unbelievable)\b'  # Hyperbole
        ]
        
        informal_count = sum(1 for pattern in informal_patterns 
                           if re.search(pattern, content_lower))
        
        # Calculate score
        if marker_count > 0:
            score = min(1.0, marker_count * 0.3)
        else:
            score = 0.5
        
        score -= informal_count * 0.2
        
        return max(0, min(1.0, score))
    
    def _has_clear_cta(self, content: str) -> bool:
        """Check if CTA is clear and actionable"""
        cta_indicators = [
            'learn more', 'visit', 'join', 'explore', 'discover',
            'read', 'check out', 'see', 'find out', 'get started',
            'register', 'sign up', 'subscribe', 'follow'
        ]
        
        content_lower = content.lower()
        return any(indicator in content_lower for indicator in cta_indicators)
    
    def _improve_cta(self, content: str) -> str:
        """Improve CTA clarity"""
        # If CTA doesn't start with an action verb, add one
        if not self._has_clear_cta(content):
            if 'regen.network' in content.lower():
                return f"🔗 Learn more at {content}"
            else:
                return f"🔗 {content}"
        return content