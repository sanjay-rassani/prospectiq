"""Build human-operated research search links (never fetched by the app)."""

from __future__ import annotations

from urllib.parse import quote_plus

from app.models import Company
from app.services.contacts.pages import candidate_people_urls, company_base_url


def research_search_links(
    company: Company,
    buyer_role: str | None = None,
) -> dict[str, str | list[str]]:
    """URLs the operator opens in their browser to find a buyer contact."""
    role = (buyer_role or "decision maker").strip() or "decision maker"
    company_name = (company.name or company.domain or "").strip()
    domain = (company.domain or "").strip()

    google_q = f'{company_name} "{role}"'
    if domain:
        google_q += f" site:{domain} OR {domain}"
    linkedin_q = f"{role} {company_name}".strip()
    google_linkedin_q = f'site:linkedin.com/in "{company_name}" {role}'

    site_pages = candidate_people_urls(company)[:6]
    return {
        "company_site": company_base_url(company),
        "site_people_pages": site_pages,
        "google_search": f"https://www.google.com/search?q={quote_plus(google_q)}",
        "google_linkedin": f"https://www.google.com/search?q={quote_plus(google_linkedin_q)}",
        "linkedin_search": (
            "https://www.linkedin.com/search/results/people/"
            f"?keywords={quote_plus(linkedin_q)}"
        ),
        "google_query_label": google_q,
        "linkedin_query_label": linkedin_q,
    }
