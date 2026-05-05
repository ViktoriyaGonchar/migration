from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from leads.forms import LeadForm


def seo_landing(request):
    return render(request, "public/seo_landing.html")


@require_http_methods(["GET", "POST"])
def app_index(request):
    form = LeadForm()
    success = request.GET.get("success") == "1"
    contacts_active = success

    if request.method == "POST":
        form = LeadForm(request.POST)
        contacts_active = True
        if form.is_valid():
            lead = form.save(commit=False)
            lead.source = "app_token" if request.GET.get("token") else "app"
            lead.save()
            return redirect_with_success(request)

    return render(
        request,
        "public/app_index.html",
        {
            "lead_form": form,
            "success": success,
            "contacts_active": contacts_active,
        },
    )


def redirect_with_success(request):
    return_url = f"{reverse('public:app')}?success=1"
    token = request.GET.get("token")
    if token:
        return_url = f"{return_url}&token={token}"
    return redirect(return_url)
