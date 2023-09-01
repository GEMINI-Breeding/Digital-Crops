import cv2
import pandas as pd
import numpy as np


# if main
if __name__ == '__main__':
    # Load image using opencv
    img = cv2.imread('../build/rendered_images/annotations/view00000/RGB_rendering.jpeg')

    if 0:
        # Load annotation text file
        with open('data.txt', 'r') as f:
            lines = f.readlines()
            for line in lines:
                # Split line by spaces
                line = line.split(' ')
                # Convert to integers
                line = [int(x) for x in line]
                # Draw rectangle
                cv2.rectangle(img, (line[0], line[1]), (line[2], line[3]), (0, 255, 0), 2)
    # Load semantic segmentation text file using pandas. convert all values to integers
    segmentation = pd.read_csv('../build/rendered_images/annotations/view00000/semantic_segmentation.txt', sep=' ', header=None).values.astype(int)
    segmentation = segmentation[:,:-1]

    # Get the unique values from the segmentation
    unique = np.unique(segmentation)
    
    # Map the unique values into colors. The length of the unique values is the number of classes
    np.random.seed(0)
    if 0:
        colors = np.random.randint(0, 255, size=(len(unique), 3), dtype=np.uint8)
    else:
        # Generate colormap using matplotlib
        import matplotlib.pyplot as plt
        import matplotlib.cm as cm
        colors = cm.get_cmap('tab20', len(unique))
        colors = (colors.colors*255).astype(np.uint8)
        colors = colors[:, :3]
        
    # Create a dictionary to map the unique values to colors
    color_dict = dict(zip(unique, colors))

    # Loop through all pixels
    if 0:
        canvas = np.zeros((segmentation.shape[0], segmentation.shape[1], 3),dtype=np.uint8)
        for i in range(segmentation.shape[0]):
            for j in range(segmentation.shape[1]):
                # Get class
                c = segmentation[i, j]
                # Get color
                color = color_dict[c]
                # Draw pixel
                canvas[i, j, :] = color
    else:
        canvas = np.zeros((segmentation.shape[0], segmentation.shape[1], 3),dtype=np.uint8)
        if 0:
            for c in unique:
                # Get binary mask
                mask = (segmentation == c).astype(np.uint8)
                # Get color
                color = color_dict[c]
                # Draw mask
                canvas += mask[:, :, np.newaxis] * color
        else:
            c = unique[4]
            mask = (segmentation == c).astype(np.uint8)
            # Get color
            color = color_dict[c]
            # Draw mask
            canvas += mask[:, :, np.newaxis] * color
        
    
    # Show image
    cv2.imshow('canvas', canvas)
    cv2.waitKey(0)

    # Save canvas
    cv2.imwrite('canvas.png', canvas)

    # Read bounding box annotations. This is a list of xmin ymin xmax ymax in percentages
    #classes = {"branches","clusters","leaves","trunks"}
    classes = {"clusters"}
    width = img.shape[1]
    height = img.shape[0]
    for idx, obj_class in enumerate(classes):
        annotations = pd.read_csv(f'../build/rendered_images/annotations/view00000/rectangular_labels_{obj_class}.txt', sep=' ', header=None).values.astype(float)

        annotations = annotations[:, 1:].astype(np.float32)

        # Convert the bounding boxes to COCO JSON format.
        x_c, y_c, w, h = np.rollaxis(annotations, 1)
        x_min = (x_c - w / 2) * width
        y_min = ((1 - y_c) - h / 2) * height
        w = w * width
        h = h * height
        coords = np.dstack([x_min, y_min, w, h])[0].astype(np.int32)
        # Loop through all bounding boxes
        for coord in coords:

            # Get color
            color = color_dict[unique[idx]]
            # Draw bounding box
            cv2.rectangle(img, (coord[0], coord[1]), (coord[0]+coord[2], coord[1]+coord[3]), color.tolist(), 2)
            break

    # Show image
    cv2.imshow('img', img)
    cv2.waitKey(0)