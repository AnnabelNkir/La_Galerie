from django.http  import HttpResponse

# Create your views here.
def welcome(request):
    return HttpResponse('Welcome to the Moringa Tribune')