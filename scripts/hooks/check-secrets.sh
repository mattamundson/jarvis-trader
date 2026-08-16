#!/bin/bash
#
# JARVIS TRADER — Pre-commit Secret Detection Hook
# Scans staged files for API key patterns and blocks commits containing secrets
#
# Installation:
#   chmod +x scripts/check-secrets.sh
#   ln -s ../../scripts/check-secrets.sh .git/hooks/pre-commit
#
# This hook will run automatically before every git commit.
# If secrets are found, the commit is blocked with instructions.

set -e

# Color codes for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Patterns to detect (API keys, tokens, secrets)
PATTERNS=(
    # Anthropic API Keys
    'sk-ant-api[0-9]*-[A-Za-z0-9_\-]*'

    # Twilio Account SID and Auth Token
    'AC[a-zA-Z0-9]{32}'  # Twilio SID pattern
    'TWILIO_AUTH_TOKEN\s*[=:]\s*[A-Za-z0-9_\-]{32,}'
    'TWILIO_ACCOUNT_SID\s*[=:]\s*[A-Za-z0-9]{34}'

    # Polygon API keys
    'POLYGON_API_KEY\s*[=:]\s*[A-Za-z0-9_\-]{20,}'
    'pk_[A-Za-z0-9_\-]{20,}'  # Polygon key prefix

    # Google OAuth Client Secrets
    'GOCSPX-[A-Za-z0-9_\-]{20,}'
    'client_secret.*\.json'
    '"client_secret"\s*:\s*"[A-Za-z0-9_\-]{20,}"'

    # AWS Access Keys
    'AKIA[0-9A-Z]{16}'
    'aws_secret_access_key\s*[=:]\s*[A-Za-z0-9/+=]{40,}'

    # Generic secret patterns
    'password\s*[=:]\s*["\x27][^\s]+["\x27]'
    'secret\s*[=:]\s*["\x27][^\s]+["\x27]'
)

# Filename patterns that are themselves a red flag, regardless of content
# (credential exports named after their own shape, e.g. a 1Password/Perplexity
# CSV dump — see INC-15, Secret-Value.csv sat undetected for 48 days because
# no check ever looked at the filename, only KEY=value-style content patterns)
FILENAME_PATTERNS=(
    '[Ss]ecret.*\.csv$'
    '[Cc]redential.*\.csv$'
    '\.pem$'
    '\.p12$'
    '\.pfx$'
)

# Files to scan (staged files only)
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM)

# If no staged files, exit successfully
if [ -z "$STAGED_FILES" ]; then
    exit 0
fi

# Counter for found secrets
SECRETS_FOUND=0
FOUND_FILES=()

# Scan each staged file
for file in $STAGED_FILES; do
    # Skip .gitignore and .git directory
    if [[ "$file" == ".gitignore" ]] || [[ "$file" == .git/* ]]; then
        continue
    fi

    # Check filename shape first — catches secret-export files even when
    # their content doesn't match a KEY=value pattern (e.g. a CSV export)
    for fnpattern in "${FILENAME_PATTERNS[@]}"; do
        if echo "$file" | grep -E "$fnpattern" > /dev/null 2>&1; then
            SECRETS_FOUND=$((SECRETS_FOUND + 1))
            if [[ ! " ${FOUND_FILES[@]} " =~ " ${file} " ]]; then
                FOUND_FILES+=("$file")
            fi
            echo -e "${RED}[SECRET-SHAPED FILENAME]${NC} File: $file"
            echo -e "  Pattern: $fnpattern"
            echo ""
        fi
    done

    # Skip binary files for content scanning
    if ! git cat-file -t :0:"$file" 2>/dev/null | grep -q "blob"; then
        continue
    fi

    # Get staged file content
    FILE_CONTENT=$(git show ":0:$file" 2>/dev/null)

    # Check against each pattern
    for pattern in "${PATTERNS[@]}"; do
        if echo "$FILE_CONTENT" | grep -E "$pattern" > /dev/null 2>&1; then
            SECRETS_FOUND=$((SECRETS_FOUND + 1))
            if [[ ! " ${FOUND_FILES[@]} " =~ " ${file} " ]]; then
                FOUND_FILES+=("$file")
            fi

            # Debug: show which pattern matched
            echo -e "${RED}[SECRET DETECTED]${NC} File: $file"
            echo -e "  Pattern: $pattern"
            echo -e "  Matches:"
            echo "$FILE_CONTENT" | grep -E "$pattern" | head -3 | sed 's/^/    /'
            echo ""
        fi
    done
done

# If secrets found, block the commit
if [ $SECRETS_FOUND -gt 0 ]; then
    echo ""
    echo -e "${RED}❌ COMMIT BLOCKED: $SECRETS_FOUND secret(s) detected!${NC}"
    echo ""
    echo -e "${YELLOW}Files with secrets:${NC}"
    for file in "${FOUND_FILES[@]}"; do
        echo "  - $file"
    done
    echo ""
    echo -e "${YELLOW}What to do:${NC}"
    echo "  1. Remove sensitive data from the files above"
    echo "  2. For API keys, use environment variables or .env (which is in .gitignore)"
    echo "  3. Use .env.example for templates with placeholder values"
    echo "  4. Stage the cleaned files: git add <file>"
    echo "  5. Try commit again"
    echo ""
    echo -e "${YELLOW}Did you hardcode a real API key?${NC}"
    echo "  1. Revoke the key immediately at the service console"
    echo "  2. Generate a new key"
    echo "  3. Use the new key in .env"
    echo "  4. Follow SECURITY_REMEDIATION.md for full details"
    echo ""

    exit 1
fi

# All clear
echo -e "${GREEN}✓ No secrets detected. Commit approved.${NC}"
exit 0
