from django.shortcuts import render, redirect
from gallery.models import Photo, Location

# Create your views here.
def index(request):
    photos = Photo.show_all_photos()
    return render(request, "gallery/index.html", context={"photos":photos})
