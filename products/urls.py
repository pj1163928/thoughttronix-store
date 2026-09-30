from django.urls import path

from . import views

app_name = "products"

urlpatterns = [
    path("", views.CatalogView.as_view(), name="catalog"),
    path("products/<slug:slug>/", views.ProductDetailView.as_view(), name="detail"),
    path("categories/<slug:slug>/", views.CategoryView.as_view(), name="category"),
    # Back office — staff-only, pk URLs per the URL conventions.
    path(
        "backoffice/products/",
        views.ManageProductListView.as_view(),
        name="manage_products",
    ),
    path(
        "backoffice/products/add/",
        views.ManageProductCreateView.as_view(),
        name="manage_product_create",
    ),
    path(
        "backoffice/products/<int:pk>/edit/",
        views.ManageProductUpdateView.as_view(),
        name="manage_product_update",
    ),
    path(
        "backoffice/products/<int:pk>/delete/",
        views.ManageProductDeleteView.as_view(),
        name="manage_product_delete",
    ),
    path(
        "backoffice/products/add/stage-images/",
        views.StageProductImagesView.as_view(),
        name="stage_new_product_images",
    ),
    path(
        "backoffice/products/<int:pk>/stage-images/",
        views.StageProductImagesView.as_view(),
        name="stage_product_images",
    ),
    path(
        "backoffice/products/<int:pk>/images/extras/<int:extra_pk>/make-main/",
        views.MakeMainImageView.as_view(),
        name="manage_product_extra_make_main",
    ),
    path(
        "backoffice/products/<int:pk>/images/",
        views.ManageProductImagesView.as_view(),
        name="manage_product_images",
    ),
    path(
        "backoffice/products/<int:pk>/images/main/",
        views.UploadMainImageView.as_view(),
        name="manage_product_image_upload",
    ),
    path(
        "backoffice/products/<int:pk>/images/main/remove/",
        views.RemoveMainImageView.as_view(),
        name="manage_product_image_remove",
    ),
    path(
        "backoffice/products/<int:pk>/images/extras/add/",
        views.AddExtraImageView.as_view(),
        name="manage_product_extra_add",
    ),
    path(
        "backoffice/products/<int:pk>/images/extras/<int:extra_pk>/remove/",
        views.RemoveExtraImageView.as_view(),
        name="manage_product_extra_remove",
    ),
    path(
        "backoffice/products/<int:pk>/images/extras/<int:extra_pk>/move/",
        views.MoveExtraImageView.as_view(),
        name="manage_product_extra_move",
    ),
    path(
        "backoffice/catalog/",
        views.ManageCatalogView.as_view(),
        name="manage_catalog",
    ),
    path(
        "backoffice/categories/add/",
        views.ManageCategoryCreateView.as_view(),
        name="manage_category_create",
    ),
    path(
        "backoffice/categories/<int:pk>/edit/",
        views.ManageCategoryUpdateView.as_view(),
        name="manage_category_update",
    ),
    path(
        "backoffice/tags/add/",
        views.ManageTagCreateView.as_view(),
        name="manage_tag_create",
    ),
    path(
        "backoffice/tags/<int:pk>/edit/",
        views.ManageTagUpdateView.as_view(),
        name="manage_tag_update",
    ),
]
