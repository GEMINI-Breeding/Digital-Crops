import yaml
import cv2
import numpy as np

if __name__ == '__main__':
    
    # Create a dictionary
    data = {
        'location': 'Davis',
        'year': 2032,
        'crop_types': ['pizza', 'sushi', 'ramen'],
        'crops': [

        ]
    }

    
    # Load image using opencv
    img = cv2.imread('image.png')
    for i in range(2):
        print('Select points for row {}'.format(i))
        cv2.imshow('image', img)
        # Click image to selct points
        points = []

        # Generate a random color
        color = tuple(map(int, np.random.randint(0, 255, size=3)))

        def click_event(event, x, y, flags, params):
            if event == cv2.EVENT_LBUTTONDOWN:
                points.append((x, y))
                # Make a circle at the point
                cv2.circle(img, (x, y), 3, color, -1)
                cv2.imshow('image', img)

                # Make dictionary
                dict = {
                        'crop_type': 'Sorghum',
                        'bed': i,
                        'row': 0,
                        'X': x,
                        'Y': y,
                }
                data['crops'].append(dict)
                print(points)
        cv2.setMouseCallback('image', click_event)
        cv2.waitKey(0)

    # Write the dictionary to a YAML file
    with open('data.yaml', 'w') as outfile:
        yaml.dump(data, outfile, default_flow_style=False,sort_keys=False)
    
    