"""Намеренные секреты проекта-полигона (docs/e2e-test-plan.md).

Все значения фиктивны и предназначены только для тестов сканеров.
Использование вне проекта-полигона запрещено.
"""

# Фиктивный AWS access key — детектится Gitleaks/TruffleHog.
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"

# Фиктивный AWS Secret Access Key.
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

# Фиктивный GitHub Personal Access Token.
GITHUB_TOKEN = "ghp_0123456789abcdef0123456789abcdef0123456789"


def get_aws_credentials() -> dict[str, str]:
    """Возвращает фиктивные credentials (плохая практика — хардкод)."""
    return {
        "aws_access_key_id": AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
    }
